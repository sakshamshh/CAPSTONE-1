import json
import logging
import math
import socket
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import uuid

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SUPABASE_URL = "https://zpgkekwrrzmhvtxoihqs.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpwZ2tla3dycnptaHZ0eG9paHFzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NzcwNjIzMiwiZXhwIjoyMDkzMjgyMjMyfQ.t6oa83YL1W53KFs2jaye-naGQ8WGMYHUVNQ1K-AlvJI"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Ambulance Radius Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

TRIGGER_RADIUS_METERS = 50.0

last_ambulance_update: Optional[Dict] = None
last_broadcast: Optional[Dict] = None


class AmbulanceLocation(BaseModel):
    id: Optional[str] = "ambulance"
    latitude: float
    longitude: float
    timestamp: Optional[str] = None


class TrafficLightModel(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = "Traffic Light"
    latitude: float
    longitude: float


class EmergencyModel(BaseModel):
    ambulance_id: str
    patient_latitude: float
    patient_longitude: float
    hospital_id: str


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.ambulance_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    async def connect_ambulance(self, websocket: WebSocket, ambulance_id: str):
        await websocket.accept()
        self.ambulance_connections[ambulance_id] = websocket

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    def disconnect_ambulance(self, ambulance_id: str):
        if ambulance_id in self.ambulance_connections:
            del self.ambulance_connections[ambulance_id]

    async def broadcast(self, message: dict):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)

    async def send_to_ambulance(self, ambulance_id: str, message: dict):
        ws = self.ambulance_connections.get(ambulance_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect_ambulance(ambulance_id)


manager = ConnectionManager()

DISCOVERY_PORT = 9999
DISCOVERY_MESSAGE = b"CAPSTONE_DISCOVER"
SERVER_PORT = 8000


def start_discovery_server():
    def discovery_loop():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", DISCOVERY_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data.strip() != DISCOVERY_MESSAGE:
                    continue
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as temp:
                    temp.connect(addr)
                    local_ip = temp.getsockname()[0]
                response = json.dumps({"host": local_ip, "port": SERVER_PORT}).encode("utf-8")
                sock.sendto(response, addr)
            except Exception as exc:
                logging.debug(f"Discovery error: {exc}")
                continue

    threading.Thread(target=discovery_loop, daemon=True).start()


start_discovery_server()


def haversine_distance(lat1, lon1, lat2, lon2):
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def format_timestamp(timestamp=None):
    return timestamp or datetime.utcnow().isoformat() + "Z"


def get_traffic_lights():
    return supabase.table("traffic_lights").select("*").execute().data


def build_status_message(location: AmbulanceLocation):
    lights = get_traffic_lights()
    results = []
    any_triggered = False
    for tl in lights:
        distance = haversine_distance(location.latitude, location.longitude, tl["latitude"], tl["longitude"])
        triggered = distance <= TRIGGER_RADIUS_METERS
        if triggered:
            any_triggered = True
        results.append({"id": tl["id"], "name": tl["name"], "distance_meters": round(distance, 1), "triggered": triggered})

    return {
        "status": "triggered" if any_triggered else "clear",
        "traffic_lights": results,
        "radius_meters": TRIGGER_RADIUS_METERS,
        "ambulance": {
            "id": location.id or "ambulance",
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timestamp": format_timestamp(location.timestamp),
        },
    }


@app.get("/")
def homepage():
    return HTMLResponse(content="<h1>Ambulance Server</h1><p><a href='/map'>Map</a> | <a href='/navigate'>Navigate</a> | <a href='/hq'>HQ Dashboard</a> | <a href='/status'>Status</a></p>")


@app.get("/status")
def status_check():
    return {"status": "ok", "active_clients": len(manager.active_connections), "trigger_radius_meters": TRIGGER_RADIUS_METERS}


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/traffic-lights")
def get_lights():
    return get_traffic_lights()


@app.post("/traffic-lights")
def add_traffic_light(tl: TrafficLightModel):
    new_tl = {"id": tl.id or str(uuid.uuid4())[:8], "name": tl.name or "Traffic Light", "latitude": tl.latitude, "longitude": tl.longitude}
    supabase.table("traffic_lights").insert(new_tl).execute()
    return new_tl


@app.delete("/traffic-lights/{tl_id}")
def delete_traffic_light(tl_id: str):
    supabase.table("traffic_lights").delete().eq("id", tl_id).execute()
    return {"status": "deleted"}


@app.get("/ambulances")
def get_ambulances():
    return supabase.table("ambulances").select("*").execute().data


@app.get("/hospitals")
def get_hospitals():
    return supabase.table("hospitals").select("*").execute().data


@app.get("/emergencies")
def get_emergencies():
    return supabase.table("emergencies").select("*").execute().data


@app.post("/emergencies")
async def create_emergency(emergency: EmergencyModel):
    new_emergency = {
        "id": str(uuid.uuid4()),
        "ambulance_id": emergency.ambulance_id,
        "patient_latitude": emergency.patient_latitude,
        "patient_longitude": emergency.patient_longitude,
        "hospital_id": emergency.hospital_id,
        "status": "dispatched"
    }
    supabase.table("emergencies").insert(new_emergency).execute()
    supabase.table("ambulances").update({"status": "dispatched"}).eq("id", emergency.ambulance_id).execute()

    hospital = supabase.table("hospitals").select("*").eq("id", emergency.hospital_id).execute().data[0]
    await manager.send_to_ambulance(emergency.ambulance_id, {
        "type": "dispatch",
        "emergency_id": new_emergency["id"],
        "patient_latitude": emergency.patient_latitude,
        "patient_longitude": emergency.patient_longitude,
        "hospital": hospital
    })
    return new_emergency


@app.post("/emergencies/{emergency_id}/picked-up")
async def patient_picked_up(emergency_id: str):
    supabase.table("emergencies").update({"status": "en_route"}).eq("id", emergency_id).execute()
    return {"status": "en_route"}


@app.post("/emergencies/{emergency_id}/complete")
async def complete_emergency(emergency_id: str):
    emergency = supabase.table("emergencies").select("*").eq("id", emergency_id).execute().data[0]
    supabase.table("emergencies").update({"status": "complete"}).eq("id", emergency_id).execute()
    supabase.table("ambulances").update({"status": "idle"}).eq("id", emergency["ambulance_id"]).execute()
    return {"status": "complete"}


@app.post("/ambulance")
async def ambulance_update(location: AmbulanceLocation):
    message = build_status_message(location)
    global last_ambulance_update, last_broadcast
    last_ambulance_update = message["ambulance"]
    last_broadcast = message
    supabase.table("ambulances").update({
        "latitude": location.latitude,
        "longitude": location.longitude,
        "last_seen": format_timestamp()
    }).eq("id", location.id).execute()
    await manager.broadcast(message)
    return JSONResponse(content=message)


@app.get("/ambulance/latest")
def latest_ambulance():
    if last_ambulance_update is None:
        raise HTTPException(status_code=404, detail="No ambulance update received yet")
    return last_ambulance_update


@app.get("/mobile")
def mobile_sender():
    html_path = Path(__file__).resolve().parent / "mobile_sender.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


@app.websocket("/ws/traffic-light")
async def traffic_light_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        lights = get_traffic_lights()
        await websocket.send_json({"status": "connected", "traffic_lights": lights, "radius_meters": TRIGGER_RADIUS_METERS})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logging.warning("WebSocket error: %s", exc)
        manager.disconnect(websocket)


@app.websocket("/ws/ambulance/{ambulance_id}")
async def ambulance_ws(websocket: WebSocket, ambulance_id: str):
    await manager.connect_ambulance(websocket, ambulance_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_ambulance(ambulance_id)
    except Exception as exc:
        logging.warning("Ambulance WS error: %s", exc)
        manager.disconnect_ambulance(ambulance_id)


@app.get("/navigate")
def navigate_page():
    html = """
<!DOCTYPE html>
<html>
<head>
  <title>Ambulance Navigation</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css"/>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #0a1224; color: #fff; display: flex; flex-direction: column; height: 100vh; }
    #topbar { background: #121b36; padding: 10px 14px; z-index: 1000; }
    #topbar h2 { font-size: 15px; color: #6fc5ff; margin-bottom: 6px; }
    #status { font-size: 12px; color: #a8b0d0; }
    #distance { font-size: 20px; font-weight: bold; margin: 4px 0; }
    #btnRow { display: flex; gap: 6px; margin-top: 6px; }
    button { flex: 1; padding: 8px; border: none; border-radius: 8px; font-size: 13px; font-weight: bold; cursor: pointer; }
    #btnStart { background: #2ecc71; color: #fff; }
    #btnStop { background: #e74c3c; color: #fff; }
    #btnForce { background: #f39c12; color: #fff; }
    #btnAdd { background: #3498db; color: #fff; }
    #map { flex: 1; }
    #panel { position: fixed; right: 0; top: 0; bottom: 0; width: 240px; background: #121b36; padding: 12px; overflow-y: auto; z-index: 2000; transform: translateX(100%); transition: transform 0.3s; }
    #panel.open { transform: translateX(0); }
    #panel h3 { color: #6fc5ff; margin-bottom: 10px; font-size: 14px; }
    .tl-item { background: #1e2a4a; border-radius: 8px; padding: 8px; margin-bottom: 8px; font-size: 13px; }
    .tl-item span { display: block; color: #fff; font-weight: bold; }
    .tl-item small { color: #a8b0d0; }
    .tl-delete { background: #e74c3c; color: #fff; border: none; border-radius: 6px; padding: 4px 8px; cursor: pointer; float: right; font-size: 11px; margin-top: 4px; }
    #closePanel { background: #2f3450; color: #fff; border: none; border-radius: 6px; padding: 6px 10px; cursor: pointer; margin-bottom: 10px; width: 100%; }
    #addForm { margin-top: 10px; }
    #addForm input { width: 100%; padding: 6px; border-radius: 6px; border: none; background: #2f3450; color: #fff; margin-bottom: 6px; font-size: 13px; }
    #addForm button { width: 100%; background: #2ecc71; color: #fff; border: none; border-radius: 6px; padding: 8px; cursor: pointer; font-weight: bold; }
    #triggerAlert { display: none; position: fixed; top: 0; left: 0; right: 0; background: #e74c3c; color: #fff; text-align: center; padding: 14px; font-size: 18px; font-weight: bold; z-index: 9999; }
    #mapInstruct { display: none; position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%); background: #f39c12; color: #000; padding: 10px 18px; border-radius: 20px; font-weight: bold; font-size: 13px; z-index: 3000; }
    #dispatchAlert { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.85); z-index: 9998; align-items: center; justify-content: center; flex-direction: column; }
    #dispatchAlert.show { display: flex; }
    #dispatchBox { background: #121b36; border-radius: 16px; padding: 24px; text-align: center; max-width: 300px; }
    #dispatchBox h2 { color: #e74c3c; margin-bottom: 10px; }
    #dispatchBox p { color: #fff; margin-bottom: 16px; font-size: 14px; }
    #btnAccept { background: #2ecc71; color: #fff; border: none; border-radius: 10px; padding: 12px 24px; font-size: 16px; font-weight: bold; cursor: pointer; width: 100%; }
  </style>
</head>
<body>
  <div id="triggerAlert">TRAFFIC LIGHT TRIGGERED</div>
  <div id="mapInstruct">Tap on map to place traffic light</div>
  <div id="dispatchAlert">
    <div id="dispatchBox">
      <h2>EMERGENCY DISPATCH</h2>
      <p id="dispatchInfo">Patient location received.</p>
      <button id="btnAccept" onclick="acceptDispatch()">Accept & Navigate</button>
    </div>
  </div>
  <div id="topbar">
    <h2>Ambulance Navigation</h2>
    <div id="status">Waiting for GPS...</div>
    <div id="distance">— m to nearest light</div>
    <div id="btnRow">
      <button id="btnStart" onclick="startNav()">Start</button>
      <button id="btnStop" onclick="stopNav()">Stop</button>
      <button id="btnForce" onclick="forceTrigger()">Force</button>
      <button id="btnAdd" onclick="openPanel()">Lights</button>
    </div>
  </div>
  <div id="map"></div>
  <div id="panel">
    <button id="closePanel" onclick="closePanel()">Close</button>
    <h3>Traffic Lights</h3>
    <div id="tlList"></div>
    <div id="addForm">
      <input id="tlName" placeholder="Light name"/>
      <button onclick="startPinMode()">Pin on Map</button>
    </div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.js"></script>
  <script>
    var ambulanceId = new URLSearchParams(location.search).get('id') || 'amb-1';
    var myPos = null;
    var watchId = null;
    var sendInterval = null;
    var triggered = false;
    var pinMode = false;
    var tlMarkers = {};
    var tlCircles = {};
    var nearestTL = null;
    var currentEmergency = null;
    var phase = 'idle';

    var map = L.map('map').setView([30.356472, 76.371972], 18);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    var ambulanceIcon = L.divIcon({html: '🚑', className: '', iconSize: [30,30]});
    var lightIcon = L.divIcon({html: '🚦', className: '', iconSize: [30,30]});
    var patientIcon = L.divIcon({html: '🏥', className: '', iconSize: [30,30]});
    var ambulanceMarker = null;
    var patientMarker = null;
    var routingControl = L.Routing.control({waypoints: [], show: true, addWaypoints: false, router: L.Routing.osrmv1({serviceUrl: 'https://router.project-osrm.org/route/v1'})}).addTo(map);

    var ws = new WebSocket('wss://' + location.host + '/ws/ambulance/' + ambulanceId);
    ws.onmessage = function(e) {
      var data = JSON.parse(e.data);
      if (data.type === 'dispatch') {
        currentEmergency = data;
        document.getElementById('dispatchInfo').innerText = 'Patient at ' + data.patient_latitude.toFixed(5) + ', ' + data.patient_longitude.toFixed(5) + '\nHospital: ' + data.hospital.name;
        document.getElementById('dispatchAlert').classList.add('show');
      }
    };
    ws.onclose = function() { setTimeout(function() { location.reload(); }, 3000); };

    function acceptDispatch() {
      document.getElementById('dispatchAlert').classList.remove('show');
      phase = 'to_patient';
      if (patientMarker) map.removeLayer(patientMarker);
      patientMarker = L.marker([currentEmergency.patient_latitude, currentEmergency.patient_longitude], {icon: patientIcon}).addTo(map).bindPopup('Patient').openPopup();
      if (myPos) {
        routingControl.setWaypoints([L.latLng(myPos), L.latLng(currentEmergency.patient_latitude, currentEmergency.patient_longitude)]);
      }
      document.getElementById('status').innerText = 'Navigating to patient...';
      addPickedUpButton();
    }

    function addPickedUpButton() {
      var btn = document.createElement('button');
      btn.innerText = 'Picked Up';
      btn.style.cssText = 'background:#9b59b6;color:#fff;border:none;border-radius:8px;padding:8px;font-weight:bold;cursor:pointer;flex:1;';
      btn.onclick = patientPickedUp;
      document.getElementById('btnRow').appendChild(btn);
    }

    function patientPickedUp() {
      phase = 'to_hospital';
      fetch('/emergencies/' + currentEmergency.emergency_id + '/picked-up', {method: 'POST'});
      if (patientMarker) map.removeLayer(patientMarker);
      var h = currentEmergency.hospital;
      patientMarker = L.marker([h.latitude, h.longitude], {icon: patientIcon}).addTo(map).bindPopup(h.name).openPopup();
      if (myPos) {
        routingControl.setWaypoints([L.latLng(myPos), L.latLng(h.latitude, h.longitude)]);
      }
      document.getElementById('status').innerText = 'Navigating to ' + h.name;
    }

    function loadLights() {
      fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
        Object.values(tlMarkers).forEach(m => map.removeLayer(m));
        Object.values(tlCircles).forEach(c => map.removeLayer(c));
        tlMarkers = {}; tlCircles = {};
        var list = document.getElementById('tlList');
        list.innerHTML = '';
        lights.forEach(function(tl) {
          var m = L.marker([tl.latitude, tl.longitude], {icon: lightIcon}).addTo(map).bindPopup(tl.name);
          var c = L.circle([tl.latitude, tl.longitude], {radius: 50, color: 'green', fillColor: 'green', fillOpacity: 0.2}).addTo(map);
          tlMarkers[tl.id] = m;
          tlCircles[tl.id] = c;
          var div = document.createElement('div');
          div.className = 'tl-item';
   div.innerHTML = '<button class="tl-delete" onclick="deleteLight(`'+tl.id+'`)">Delete</button><span>'+tl.name+'</span><small>'+tl.latitude.toFixed(5)+', '+tl.longitude.toFixed(5)+'</small>';<small>'+tl.latitude.toFixed(5)+', '+tl.longitude.toFixed(5)+'</small>';
          list.appendChild(div);
        });
      });
    }

    function deleteLight(id) {
      fetch('/traffic-lights/' + id, {method: 'DELETE'}).then(function() { loadLights(); });
    }

    function openPanel() { document.getElementById('panel').classList.add('open'); loadLights(); }
    function closePanel() { document.getElementById('panel').classList.remove('open'); }

    function startPinMode() {
      var name = document.getElementById('tlName').value.trim() || 'Traffic Light';
      pinMode = name;
      closePanel();
      document.getElementById('mapInstruct').style.display = 'block';
    }

    map.on('click', function(e) {
      if (!pinMode) return;
      fetch('/traffic-lights', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: pinMode, latitude: e.latlng.lat, longitude: e.latlng.lng})}).then(function() {
        pinMode = false;
        document.getElementById('mapInstruct').style.display = 'none';
        document.getElementById('tlName').value = '';
        loadLights();
      });
    });

    function startNav() {
      document.getElementById('status').innerText = 'Getting GPS...';
      watchId = navigator.geolocation.watchPosition(function(pos) {
        myPos = [pos.coords.latitude, pos.coords.longitude];
        if (!ambulanceMarker) ambulanceMarker = L.marker(myPos, {icon: ambulanceIcon}).addTo(map);
        else ambulanceMarker.setLatLng(myPos);
        map.panTo(myPos);
        if (nearestTL && phase === 'idle') routingControl.setWaypoints([L.latLng(myPos), L.latLng(nearestTL.latitude, nearestTL.longitude)]);
      }, function(err) { document.getElementById('status').innerText = 'GPS error: ' + err.message; }, {enableHighAccuracy: true, maximumAge: 2000});

      sendInterval = setInterval(function() {
        if (!myPos) return;
        fetch('/ambulance', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({latitude: myPos[0], longitude: myPos[1], id: ambulanceId})})
        .then(r => r.json()).then(function(data) {
          if (!data.traffic_lights) return;
          var nearest = data.traffic_lights.reduce((a, b) => a.distance_meters < b.distance_meters ? a : b);
          nearestTL = nearest;
          document.getElementById('distance').innerText = nearest.distance_meters + ' m to ' + nearest.name;
          data.traffic_lights.forEach(function(tl) {
            if (tlCircles[tl.id]) {
              tlCircles[tl.id].setStyle({color: tl.triggered ? 'red' : 'green', fillColor: tl.triggered ? 'red' : 'green'});
            }
          });
          if (data.status === 'triggered' && !triggered) {
            triggered = true;
            document.getElementById('triggerAlert').style.display = 'block';
            setTimeout(function() { document.getElementById('triggerAlert').style.display = 'none'; triggered = false; }, 4000);
          }
        });
      }, 2000);
    }

    function stopNav() {
      if (watchId) navigator.geolocation.clearWatch(watchId);
      if (sendInterval) clearInterval(sendInterval);
      document.getElementById('status').innerText = 'Stopped.';
    }

    function forceTrigger() {
      fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
        if (!lights.length) return;
        var tl = lights[0];
        fetch('/ambulance', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({latitude: tl.latitude, longitude: tl.longitude, id: ambulanceId})});
        document.getElementById('status').innerText = 'Force triggered!';
      });
    }

    loadLights();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/hq")
def hq_page():
    html = """
<!DOCTYPE html>
<html>
<head>
  <title>HQ Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #0a1224; color: #fff; display: flex; height: 100vh; }
    #sidebar { width: 320px; background: #121b36; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
    #map { flex: 1; }
    h2 { color: #6fc5ff; font-size: 18px; }
    h3 { color: #6fc5ff; font-size: 14px; margin-bottom: 8px; }
    .amb-item { background: #1e2a4a; border-radius: 10px; padding: 10px; cursor: pointer; margin-bottom: 8px; }
    .amb-item:hover { background: #2a3a6a; }
    .amb-name { font-weight: bold; font-size: 14px; }
    .amb-status { font-size: 12px; color: #a8b0d0; margin-top: 4px; }
    .status-idle { color: #2ecc71; }
    .status-dispatched { color: #e74c3c; }
    select, input { width: 100%; padding: 8px; border-radius: 8px; border: none; background: #2f3450; color: #fff; margin-bottom: 8px; font-size: 13px; }
    .btn { width: 100%; padding: 10px; border: none; border-radius: 8px; font-size: 14px; font-weight: bold; cursor: pointer; margin-bottom: 6px; }
    .btn-red { background: #e74c3c; color: #fff; }
    .btn-green { background: #2ecc71; color: #fff; }
    #dispatchForm { background: #1e2a4a; border-radius: 10px; padding: 12px; }
    #mapInstruct { display: none; position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #f39c12; color: #000; padding: 10px 18px; border-radius: 20px; font-weight: bold; z-index: 3000; }
  </style>
</head>
<body>
  <div id="sidebar">
    <h2>HQ Dashboard</h2>
    <div>
      <h3>Ambulances</h3>
      <div id="ambList"></div>
    </div>
    <div id="dispatchForm">
      <h3>Dispatch Emergency</h3>
      <select id="selAmb"></select>
      <select id="selHospital"></select>
      <button class="btn btn-red" onclick="startPatientPin()">Pin Patient Location on Map</button>
      <div id="patientCoords" style="font-size:12px;color:#a8b0d0;margin-bottom:8px;">No patient location set</div>
      <button class="btn btn-green" onclick="dispatchEmergency()">Dispatch</button>
    </div>
  </div>
  <div id="mapInstruct">Click on map to set patient location</div>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    var map = L.map('map').setView([30.356472, 76.371972], 16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    var ambulanceIcon = L.divIcon({html: '🚑', className: '', iconSize: [30,30]});
    var lightIcon = L.divIcon({html: '🚦', className: '', iconSize: [30,30]});
    var patientIcon = L.divIcon({html: '📍', className: '', iconSize: [30,30]});
    var hospitalIcon = L.divIcon({html: '🏥', className: '', iconSize: [30,30]});
    var ambMarkers = {};
    var patientMarker = null;
    var patientPos = null;
    var pinningPatient = false;

    function loadAll() {
      fetch('/ambulances').then(r => r.json()).then(function(ambs) {
        var list = document.getElementById('ambList');
        var sel = document.getElementById('selAmb');
        list.innerHTML = '';
        sel.innerHTML = '';
        ambs.forEach(function(a) {
          var div = document.createElement('div');
          div.className = 'amb-item';
          div.innerHTML = '<div class="amb-name">' + a.id + ' - ' + (a.driver_name || 'Unknown') + '</div><div class="amb-status status-' + a.status + '">' + a.status + '</div>';
          list.appendChild(div);
          if (a.latitude) {
            if (!ambMarkers[a.id]) ambMarkers[a.id] = L.marker([a.latitude, a.longitude], {icon: ambulanceIcon}).addTo(map).bindPopup(a.id);
            else ambMarkers[a.id].setLatLng([a.latitude, a.longitude]);
          }
          var opt = document.createElement('option');
          opt.value = a.id;
          opt.innerText = a.id + ' - ' + (a.driver_name || 'Unknown') + ' (' + a.status + ')';
          sel.appendChild(opt);
        });
      });

      fetch('/hospitals').then(r => r.json()).then(function(hospitals) {
        var sel = document.getElementById('selHospital');
        sel.innerHTML = '';
        hospitals.forEach(function(h) {
          L.marker([h.latitude, h.longitude], {icon: hospitalIcon}).addTo(map).bindPopup(h.name);
          var opt = document.createElement('option');
          opt.value = h.id;
          opt.innerText = h.name;
          sel.appendChild(opt);
        });
      });

      fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
        lights.forEach(function(tl) {
          L.marker([tl.latitude, tl.longitude], {icon: lightIcon}).addTo(map).bindPopup(tl.name);
          L.circle([tl.latitude, tl.longitude], {radius: 50, color: 'green', fillColor: 'green', fillOpacity: 0.2}).addTo(map);
        });
      });
    }

    function startPatientPin() {
      pinningPatient = true;
      document.getElementById('mapInstruct').style.display = 'block';
    }

    map.on('click', function(e) {
      if (!pinningPatient) return;
      patientPos = e.latlng;
      if (patientMarker) map.removeLayer(patientMarker);
      patientMarker = L.marker(patientPos, {icon: patientIcon}).addTo(map).bindPopup('Patient').openPopup();
      document.getElementById('patientCoords').innerText = 'Patient: ' + patientPos.lat.toFixed(5) + ', ' + patientPos.lng.toFixed(5);
      document.getElementById('mapInstruct').style.display = 'none';
      pinningPatient = false;
    });

    function dispatchEmergency() {
      if (!patientPos) { alert('Pin patient location first'); return; }
      var ambId = document.getElementById('selAmb').value;
      var hospitalId = document.getElementById('selHospital').value;
      fetch('/emergencies', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ambulance_id: ambId, patient_latitude: patientPos.lat, patient_longitude: patientPos.lng, hospital_id: hospitalId})
      }).then(r => r.json()).then(function(data) {
        alert('Emergency dispatched to ' + ambId);
        loadAll();
      });
    }

    loadAll();
    setInterval(loadAll, 5000);

    var ws = new WebSocket('wss://' + location.host + '/ws/traffic-light');
    ws.onmessage = function(e) {
      var data = JSON.parse(e.data);
      if (data.ambulance) {
        var pos = [data.ambulance.latitude, data.ambulance.longitude];
        if (!ambMarkers[data.ambulance.id]) ambMarkers[data.ambulance.id] = L.marker(pos, {icon: ambulanceIcon}).addTo(map).bindPopup(data.ambulance.id);
        else ambMarkers[data.ambulance.id].setLatLng(pos);
      }
    };
    ws.onclose = function() { setTimeout(function() { location.reload(); }, 3000); };
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/map")
def map_page():
    html = """
<!DOCTYPE html>
<html>
<head>
  <title>Ambulance Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>body{margin:0;}#map{height:100vh;width:100%;}</style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    var map = L.map('map').setView([30.356472, 76.371972], 18);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
    var tlMarkers = {}, tlCircles = {};
    var ambulanceIcon = L.divIcon({html: '🚑', className: '', iconSize: [30,30]});
    var lightIcon = L.divIcon({html: '🚦', className: '', iconSize: [30,30]});
    var ambulanceMarker = null;
    function loadLights() {
      fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
        lights.forEach(function(tl) {
          tlMarkers[tl.id] = L.marker([tl.latitude, tl.longitude], {icon: lightIcon}).addTo(map).bindPopup(tl.name);
          tlCircles[tl.id] = L.circle([tl.latitude, tl.longitude], {radius: 50, color: 'green', fillColor: 'green', fillOpacity: 0.2}).addTo(map);
        });
      });
    }
    function connectWS() {
      var ws = new WebSocket('wss://' + location.host + '/ws/traffic-light');
      ws.onmessage = function(e) {
        var data = JSON.parse(e.data);
        if (!data.ambulance) return;
        var pos = [data.ambulance.latitude, data.ambulance.longitude];
        if (!ambulanceMarker) ambulanceMarker = L.marker(pos, {icon: ambulanceIcon}).addTo(map);
        else ambulanceMarker.setLatLng(pos);
        map.panTo(pos);
        if (data.traffic_lights) {
          data.traffic_lights.forEach(function(tl) {
            if (tlCircles[tl.id]) tlCircles[tl.id].setStyle({color: tl.triggered ? 'red' : 'green', fillColor: tl.triggered ? 'red' : 'green'});
          });
        }
      };
      ws.onclose = function() { setTimeout(connectWS, 2000); };
    }
    loadLights();
    connectWS();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)