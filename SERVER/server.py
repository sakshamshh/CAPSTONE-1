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
  <title>Ambulance Dispatch</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet-routing-machine@3.2.12/dist/leaflet-routing-machine.css"/>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
    body { background: #060d1a; color: #e8eaf6; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
    
    #registerScreen { position: fixed; inset: 0; background: #060d1a; display: flex; align-items: center; justify-content: center; z-index: 9999; }
    .reg-card { background: #0d1b2e; border: 1px solid #1e3a5f; border-radius: 20px; padding: 40px; width: 340px; text-align: center; }
    .reg-card .logo { font-size: 48px; margin-bottom: 16px; }
    .reg-card h1 { font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 6px; }
    .reg-card p { font-size: 13px; color: #7b8fa6; margin-bottom: 24px; }
    .reg-card input { width: 100%; padding: 12px 16px; background: #111f35; border: 1px solid #1e3a5f; border-radius: 10px; color: #fff; font-size: 14px; margin-bottom: 12px; outline: none; }
    .reg-card input:focus { border-color: #3b82f6; }
    .reg-card input::placeholder { color: #4a5f7a; }
    .btn-primary { width: 100%; padding: 13px; background: #2563eb; border: none; border-radius: 10px; color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
    .btn-primary:hover { background: #1d4ed8; }
    #regStatus { font-size: 13px; color: #7b8fa6; margin-top: 14px; min-height: 20px; }

    #pendingScreen { position: fixed; inset: 0; background: #060d1a; display: none; align-items: center; justify-content: center; z-index: 9999; }
    .pending-card { background: #0d1b2e; border: 1px solid #1e3a5f; border-radius: 20px; padding: 40px; width: 340px; text-align: center; }
    .pending-card .spinner { width: 48px; height: 48px; border: 3px solid #1e3a5f; border-top-color: #3b82f6; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .pending-card h2 { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
    .pending-card p { font-size: 13px; color: #7b8fa6; }

    #appScreen { display: none; flex-direction: column; height: 100vh; }
    
    #topbar { background: #0a1628; border-bottom: 1px solid #1a2f4e; padding: 0 16px; height: 60px; display: flex; align-items: center; gap: 12px; z-index: 100; flex-shrink: 0; }
    #topbar .amb-id { background: #1a2f4e; border-radius: 8px; padding: 4px 10px; font-size: 12px; font-weight: 600; color: #60a5fa; letter-spacing: 0.5px; }
    #topbar .phase-badge { padding: 4px 10px; border-radius: 8px; font-size: 12px; font-weight: 600; }
    .phase-idle { background: #1a2f4e; color: #7b8fa6; }
    .phase-patient { background: #1c3a1c; color: #4ade80; }
    .phase-hospital { background: #3a1c1c; color: #f87171; }
    #topbar .spacer { flex: 1; }
    #topbar .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

    #infobar { background: #0a1628; border-bottom: 1px solid #1a2f4e; padding: 10px 16px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
    #distanceDisplay { font-size: 24px; font-weight: 700; color: #fff; }
    #distanceLabel { font-size: 12px; color: #7b8fa6; margin-top: 2px; }
    #infobar .spacer { flex: 1; }
    #triggerBadge { display: none; background: #dc2626; color: #fff; font-size: 12px; font-weight: 700; padding: 6px 14px; border-radius: 20px; animation: blink 0.5s infinite; }
    @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

    #map { flex: 1; }

    #bottombar { background: #0a1628; border-top: 1px solid #1a2f4e; padding: 12px 16px; display: flex; gap: 8px; flex-shrink: 0; }
    .btn { flex: 1; padding: 12px 8px; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; }
    .btn:disabled { opacity: 0.4; cursor: not-allowed; }
    .btn-start { background: #166534; color: #4ade80; border: 1px solid #166534; }
    .btn-start:hover:not(:disabled) { background: #14532d; }
    .btn-stop { background: #7f1d1d; color: #f87171; border: 1px solid #7f1d1d; }
    .btn-force { background: #78350f; color: #fbbf24; border: 1px solid #78350f; }
    .btn-lights { background: #1e3a5f; color: #60a5fa; border: 1px solid #1e3a5f; }
    .btn-pickup { background: #4c1d95; color: #c4b5fd; border: 1px solid #4c1d95; }

    #dispatchOverlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 9000; align-items: center; justify-content: center; }
    #dispatchOverlay.show { display: flex; }
    .dispatch-card { background: #0d1b2e; border: 1px solid #dc2626; border-radius: 20px; padding: 28px; width: 320px; }
    .dispatch-card .dispatch-header { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
    .dispatch-card .dispatch-icon { font-size: 28px; }
    .dispatch-card h2 { font-size: 18px; font-weight: 700; color: #f87171; }
    .dispatch-info { background: #111f35; border-radius: 10px; padding: 12px; margin-bottom: 16px; font-size: 13px; color: #cbd5e1; line-height: 1.8; }
    .dispatch-info strong { color: #fff; }
    .btn-accept { width: 100%; padding: 14px; background: #166534; border: none; border-radius: 10px; color: #4ade80; font-size: 15px; font-weight: 700; cursor: pointer; }

    #panel { position: fixed; right: 0; top: 0; bottom: 0; width: 280px; background: #0a1628; border-left: 1px solid #1a2f4e; padding: 16px; overflow-y: auto; z-index: 2000; transform: translateX(100%); transition: transform 0.3s; }
    #panel.open { transform: translateX(0); }
    #panel h3 { font-size: 14px; font-weight: 600; color: #60a5fa; margin-bottom: 12px; }
    .tl-card { background: #0d1b2e; border: 1px solid #1a2f4e; border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
    .tl-card .tl-icon { font-size: 20px; }
    .tl-card .tl-info { flex: 1; }
    .tl-card .tl-name { font-size: 13px; font-weight: 600; }
    .tl-card .tl-coords { font-size: 11px; color: #7b8fa6; margin-top: 2px; }
    .tl-del { background: #7f1d1d; border: none; border-radius: 6px; color: #f87171; padding: 4px 8px; font-size: 11px; cursor: pointer; }
    #panel input { width: 100%; padding: 10px 12px; background: #111f35; border: 1px solid #1a2f4e; border-radius: 8px; color: #fff; font-size: 13px; margin-bottom: 8px; outline: none; }
    #panel input:focus { border-color: #3b82f6; }
    .btn-pin { width: 100%; padding: 10px; background: #1e3a5f; border: none; border-radius: 8px; color: #60a5fa; font-size: 13px; font-weight: 600; cursor: pointer; margin-bottom: 8px; }
    .btn-close-panel { width: 100%; padding: 8px; background: transparent; border: 1px solid #1a2f4e; border-radius: 8px; color: #7b8fa6; font-size: 13px; cursor: pointer; margin-bottom: 16px; }

    #mapInstruct { display: none; position: fixed; bottom: 90px; left: 50%; transform: translateX(-50%); background: #f59e0b; color: #000; padding: 10px 20px; border-radius: 20px; font-weight: 600; font-size: 13px; z-index: 3000; }
  </style>
</head>
<body>

<div id="registerScreen">
  <div class="reg-card">
    <div class="logo">🚑</div>
    <h1>Ambulance Driver</h1>
    <p>Register to receive emergency dispatches</p>
    <input id="driverName" placeholder="Your full name" />
    <input id="driverVehicle" placeholder="Vehicle number (e.g. PB-11-1234)" />
    <button class="btn-primary" onclick="register()">Request Access</button>
    <div id="regStatus"></div>
  </div>
</div>

<div id="pendingScreen">
  <div class="pending-card">
    <div class="spinner"></div>
    <h2>Awaiting Approval</h2>
    <p>Your request has been sent to HQ. Please wait for approval.</p>
  </div>
</div>

<div id="appScreen">
  <div id="topbar">
    <span class="amb-id" id="ambIdBadge">AMB</span>
    <span class="phase-badge phase-idle" id="phaseBadge">STANDBY</span>
    <div class="spacer"></div>
    <div class="status-dot"></div>
  </div>
  <div id="infobar">
    <div>
      <div id="distanceDisplay">— m</div>
      <div id="distanceLabel">to nearest traffic light</div>
    </div>
    <div class="spacer"></div>
    <div id="triggerBadge">🚨 TRIGGERED</div>
  </div>
  <div id="map"></div>
  <div id="bottombar">
    <button class="btn btn-start" id="btnStart" onclick="startNav()">▶ Start</button>
    <button class="btn btn-stop" id="btnStop" onclick="stopNav()" disabled>■ Stop</button>
    <button class="btn btn-force" onclick="forceTrigger()">⚡ Force</button>
    <button class="btn btn-lights" onclick="openPanel()">🚦 Lights</button>
  </div>
</div>

<div id="dispatchOverlay">
  <div class="dispatch-card">
    <div class="dispatch-header">
      <span class="dispatch-icon">🚨</span>
      <h2>EMERGENCY DISPATCH</h2>
    </div>
    <div class="dispatch-info" id="dispatchInfo"></div>
    <button class="btn-accept" onclick="acceptDispatch()">✓ Accept & Navigate</button>
  </div>
</div>

<div id="panel">
  <button class="btn-close-panel" onclick="closePanel()">✕ Close</button>
  <h3>🚦 Traffic Lights</h3>
  <div id="tlList"></div>
  <input id="tlName" placeholder="Light name (e.g. Gate 2)" />
  <button class="btn-pin" onclick="startPinMode()">📍 Tap Map to Place</button>
</div>

<div id="mapInstruct">📍 Tap map to place traffic light</div>

<script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
<script>
  var MAPTILER_KEY = 'oeqoZ7jmF643lIa3lxQ3';
  var ambulanceId = null;
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
  var ws = null;
  var map = null;
  var ambulanceMarker = null;
  var destinationMarker = null;

  function register() {
    var name = document.getElementById('driverName').value.trim();
    var vehicle = document.getElementById('driverVehicle').value.trim();
    if (!name || !vehicle) { document.getElementById('regStatus').innerText = 'Please fill in all fields'; return; }
    document.getElementById('regStatus').innerText = 'Sending request...';
    fetch('/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({driver_name: name, vehicle: vehicle})
    }).then(r => r.json()).then(function(data) {
      if (data.id) {
        ambulanceId = data.id;
        localStorage.setItem('ambulanceId', ambulanceId);
        localStorage.setItem('ambulanceStatus', data.status);
        document.getElementById('registerScreen').style.display = 'none';
        document.getElementById('pendingScreen').style.display = 'flex';
        pollApproval();
      }
    }).catch(function() {
      document.getElementById('regStatus').innerText = 'Connection error. Try again.';
    });
  }

  function pollApproval() {
    var interval = setInterval(function() {
      fetch('/ambulances/' + ambulanceId).then(r => r.json()).then(function(data) {
        if (data.status === 'approved' || data.status === 'idle') {
          clearInterval(interval);
          launchApp();
        }
      });
    }, 3000);
  }

  function launchApp() {
    document.getElementById('pendingScreen').style.display = 'none';
    document.getElementById('appScreen').style.display = 'flex';
    document.getElementById('ambIdBadge').innerText = ambulanceId;
    initMap();
    connectWS();
    loadLights();
  }

  function initMap() {
    map = new maplibregl.Map({
      container: 'map',
      style: 'https://api.maptiler.com/maps/dataviz-dark/style.json?key=' + MAPTILER_KEY,
      center: [76.371972, 30.356472],
      zoom: 16
    });
  }

  function connectWS() {
    ws = new WebSocket('wss://' + location.host + '/ws/ambulance/' + ambulanceId);
    ws.onmessage = function(e) {
      var data = JSON.parse(e.data);
      if (data.type === 'dispatch') {
        currentEmergency = data;
        document.getElementById('dispatchInfo').innerHTML =
          '<strong>Patient:</strong> ' + data.patient_latitude.toFixed(5) + ', ' + data.patient_longitude.toFixed(5) +
          '<br><strong>Hospital:</strong> ' + data.hospital.name +
          '<br><strong>Distance:</strong> Calculating...';
        document.getElementById('dispatchOverlay').classList.add('show');
      }
    };
    ws.onclose = function() { setTimeout(connectWS, 3000); };
  }

  function acceptDispatch() {
    document.getElementById('dispatchOverlay').classList.remove('show');
    phase = 'to_patient';
    document.getElementById('phaseBadge').className = 'phase-badge phase-patient';
    document.getElementById('phaseBadge').innerText = 'TO PATIENT';
    document.getElementById('distanceLabel').innerText = 'to patient';
    if (destinationMarker) destinationMarker.remove();
    var el = document.createElement('div');
    el.innerHTML = '📍';
    el.style.fontSize = '28px';
    destinationMarker = new maplibregl.Marker({element: el}).setLngLat([currentEmergency.patient_longitude, currentEmergency.patient_latitude]).addTo(map);
    addPickupButton();
  }

  function addPickupButton() {
    var bar = document.getElementById('bottombar');
    var btn = document.createElement('button');
    btn.className = 'btn btn-pickup';
    btn.id = 'btnPickup';
    btn.innerText = '✓ Picked Up';
    btn.onclick = patientPickedUp;
    bar.appendChild(btn);
  }

  function patientPickedUp() {
    phase = 'to_hospital';
    fetch('/emergencies/' + currentEmergency.emergency_id + '/picked-up', {method: 'POST'});
    document.getElementById('phaseBadge').className = 'phase-badge phase-hospital';
    document.getElementById('phaseBadge').innerText = 'TO HOSPITAL';
    document.getElementById('distanceLabel').innerText = 'to ' + currentEmergency.hospital.name;
    var btn = document.getElementById('btnPickup');
    if (btn) btn.remove();
    if (destinationMarker) destinationMarker.remove();
    var el = document.createElement('div');
    el.innerHTML = '🏥';
    el.style.fontSize = '28px';
    destinationMarker = new maplibregl.Marker({element: el}).setLngLat([currentEmergency.hospital.longitude, currentEmergency.hospital.latitude]).addTo(map);
  }

  function loadLights() {
    fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
      Object.keys(tlMarkers).forEach(function(id) { tlMarkers[id].remove(); });
      tlMarkers = {};
      var list = document.getElementById('tlList');
      list.innerHTML = '';
      lights.forEach(function(tl) {
        var el = document.createElement('div');
        el.innerHTML = '🚦';
        el.style.fontSize = '24px';
        tlMarkers[tl.id] = new maplibregl.Marker({element: el}).setLngLat([tl.longitude, tl.latitude]).addTo(map);
        var card = document.createElement('div');
        card.className = 'tl-card';
        card.innerHTML = '<span class="tl-icon">🚦</span><div class="tl-info"><div class="tl-name">'+tl.name+'</div><div class="tl-coords">'+tl.latitude.toFixed(5)+', '+tl.longitude.toFixed(5)+'</div></div><button class="tl-del" onclick="deleteLight(`'+tl.id+'`)">✕</button>';
        list.appendChild(card);
      });
    });
  }

  function deleteLight(id) {
    fetch('/traffic-lights/' + id, {method: 'DELETE'}).then(function() { loadLights(); });
  }

  function openPanel() { document.getElementById('panel').classList.add('open'); }
  function closePanel() { document.getElementById('panel').classList.remove('open'); }

  function startPinMode() {
    var name = document.getElementById('tlName').value.trim() || 'Traffic Light';
    pinMode = name;
    closePanel();
    document.getElementById('mapInstruct').style.display = 'block';
  }

  map && map.on('click', function(e) {
    if (!pinMode) return;
    fetch('/traffic-lights', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: pinMode, latitude: e.lngLat.lat, longitude: e.lngLat.lng})}).then(function() {
      pinMode = false;
      document.getElementById('mapInstruct').style.display = 'none';
      document.getElementById('tlName').value = '';
      loadLights();
    });
  });

  function startNav() {
    document.getElementById('btnStart').disabled = true;
    document.getElementById('btnStop').disabled = false;
    watchId = navigator.geolocation.watchPosition(function(pos) {
      myPos = [pos.coords.longitude, pos.coords.latitude];
      if (!ambulanceMarker) {
        var el = document.createElement('div');
        el.innerHTML = '🚑';
        el.style.fontSize = '28px';
        ambulanceMarker = new maplibregl.Marker({element: el}).setLngLat(myPos).addTo(map);
      } else {
        ambulanceMarker.setLngLat(myPos);
      }
      map.easeTo({center: myPos, zoom: 17});
    }, function(err) {}, {enableHighAccuracy: true, maximumAge: 2000});

    sendInterval = setInterval(function() {
      if (!myPos) return;
      fetch('/ambulance', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({latitude: myPos[1], longitude: myPos[0], id: ambulanceId})})
      .then(r => r.json()).then(function(data) {
        if (!data.traffic_lights) return;
        var nearest = data.traffic_lights.reduce((a, b) => a.distance_meters < b.distance_meters ? a : b);
        nearestTL = nearest;
        document.getElementById('distanceDisplay').innerText = nearest.distance_meters + ' m';
        if (data.status === 'triggered' && !triggered) {
          triggered = true;
          document.getElementById('triggerBadge').style.display = 'block';
          setTimeout(function() { document.getElementById('triggerBadge').style.display = 'none'; triggered = false; }, 4000);
        }
      });
    }, 2000);
  }

  function stopNav() {
    if (watchId) navigator.geolocation.clearWatch(watchId);
    if (sendInterval) clearInterval(sendInterval);
    document.getElementById('btnStart').disabled = false;
    document.getElementById('btnStop').disabled = true;
  }

  function forceTrigger() {
    fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
      if (!lights.length) return;
      var tl = lights[0];
      fetch('/ambulance', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({latitude: tl.latitude, longitude: tl.longitude, id: ambulanceId})});
    });
  }

  var saved = localStorage.getItem('ambulanceId');
  if (saved) {
    ambulanceId = saved;
    fetch('/ambulances/' + ambulanceId).then(r => r.json()).then(function(data) {
      if (data.status === 'approved' || data.status === 'idle' || data.status === 'dispatched') {
        launchApp();
      } else if (data.status === 'pending') {
        document.getElementById('registerScreen').style.display = 'none';
        document.getElementById('pendingScreen').style.display = 'flex';
        pollApproval();
      }
    }).catch(function() {});
  }
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
  <title>HQ Dispatch Center</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css"/>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
    body { background: #060d1a; color: #e8eaf6; height: 100vh; display: flex; overflow: hidden; }

    #sidebar { width: 340px; background: #0a1628; border-right: 1px solid #1a2f4e; display: flex; flex-direction: column; flex-shrink: 0; }
    #sidebarHeader { padding: 20px 20px 16px; border-bottom: 1px solid #1a2f4e; }
    #sidebarHeader h1 { font-size: 16px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }
    #sidebarHeader .dot { width: 8px; height: 8px; border-radius: 50%; background: #4ade80; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
    #sidebarHeader p { font-size: 12px; color: #7b8fa6; margin-top: 4px; }

    #tabs { display: flex; border-bottom: 1px solid #1a2f4e; }
    .tab { flex: 1; padding: 12px; text-align: center; font-size: 12px; font-weight: 600; color: #7b8fa6; cursor: pointer; border-bottom: 2px solid transparent; }
    .tab.active { color: #60a5fa; border-bottom-color: #3b82f6; }

    #tabContent { flex: 1; overflow-y: auto; padding: 16px; }

    .section-title { font-size: 11px; font-weight: 600; color: #7b8fa6; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 10px; }

    .amb-card { background: #0d1b2e; border: 1px solid #1a2f4e; border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: border-color 0.2s; }
    .amb-card:hover { border-color: #3b82f6; }
    .amb-card.selected { border-color: #3b82f6; background: #0f2040; }
    .amb-icon { font-size: 24px; }
    .amb-info { flex: 1; }
    .amb-name { font-size: 13px; font-weight: 600; color: #fff; }
    .amb-detail { font-size: 11px; color: #7b8fa6; margin-top: 2px; }
    .amb-status { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 6px; }
    .s-idle { background: #1a2f4e; color: #60a5fa; }
    .s-pending { background: #78350f; color: #fbbf24; }
    .s-dispatched { background: #1c3a1c; color: #4ade80; }

    .pending-card { background: #0d1b2e; border: 1px solid #78350f; border-radius: 12px; padding: 12px 14px; margin-bottom: 8px; }
    .pending-actions { display: flex; gap: 8px; margin-top: 10px; }
    .btn-approve { flex: 1; padding: 8px; background: #166534; border: none; border-radius: 8px; color: #4ade80; font-size: 12px; font-weight: 600; cursor: pointer; }
    .btn-reject { flex: 1; padding: 8px; background: #7f1d1d; border: none; border-radius: 8px; color: #f87171; font-size: 12px; font-weight: 600; cursor: pointer; }

    #dispatchPanel { padding: 16px; border-top: 1px solid #1a2f4e; }
    #dispatchPanel h3 { font-size: 12px; font-weight: 600; color: #7b8fa6; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 12px; }
    select { width: 100%; padding: 10px 12px; background: #111f35; border: 1px solid #1a2f4e; border-radius: 8px; color: #fff; font-size: 13px; margin-bottom: 8px; outline: none; }
    select:focus { border-color: #3b82f6; }
    #patientInfo { background: #111f35; border: 1px solid #1a2f4e; border-radius: 8px; padding: 10px 12px; font-size: 12px; color: #7b8fa6; margin-bottom: 8px; min-height: 38px; }
    .btn-pin-patient { width: 100%; padding: 10px; background: #1e3a5f; border: none; border-radius: 8px; color: #60a5fa; font-size: 13px; font-weight: 600; cursor: pointer; margin-bottom: 8px; }
    .btn-dispatch { width: 100%; padding: 12px; background: #dc2626; border: none; border-radius: 10px; color: #fff; font-size: 14px; font-weight: 700; cursor: pointer; }
    .btn-dispatch:hover { background: #b91c1c; }

    #map { flex: 1; }

    #mapInstruct { display: none; position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #f59e0b; color: #000; padding: 10px 20px; border-radius: 20px; font-weight: 600; font-size: 13px; z-index: 3000; }

    #toast { position: fixed; top: 20px; right: 20px; background: #166534; color: #4ade80; padding: 12px 20px; border-radius: 10px; font-size: 13px; font-weight: 600; z-index: 9999; display: none; }
  </style>
</head>
<body>
<div id="sidebar">
  <div id="sidebarHeader">
    <h1><div class="dot"></div> HQ Dispatch Center</h1>
    <p id="statsText">Loading...</p>
  </div>
  <div id="tabs">
    <div class="tab active" onclick="showTab('ambulances')">Ambulances</div>
    <div class="tab" onclick="showTab('pending')">Requests <span id="pendingCount"></span></div>
  </div>
  <div id="tabContent">
    <div id="tabAmbulances">
      <div class="section-title">Active Units</div>
      <div id="ambList"></div>
    </div>
    <div id="tabPending" style="display:none">
      <div class="section-title">Pending Requests</div>
      <div id="pendingList"></div>
    </div>
  </div>
  <div id="dispatchPanel">
    <h3>Dispatch Emergency</h3>
    <select id="selAmb"></select>
    <select id="selHospital"></select>
    <div id="patientInfo">No patient location pinned</div>
    <button class="btn-pin-patient" onclick="startPatientPin()">📍 Pin Patient on Map</button>
    <button class="btn-dispatch" onclick="dispatchEmergency()">🚨 Dispatch</button>
  </div>
</div>
<div id="mapInstruct">Click map to set patient location</div>
<div id="map"></div>
<div id="toast"></div>

<script src="https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js"></script>
<script>
  var MAPTILER_KEY = 'oeqoZ7jmF643lIa3lxQ3';
  var map = new maplibregl.Map({
    container: 'map',
    style: 'https://api.maptiler.com/maps/dataviz-dark/style.json?key=' + MAPTILER_KEY,
    center: [76.371972, 30.356472],
    zoom: 15
  });

  var ambMarkers = {};
  var tlMarkers = {};
  var patientMarker = null;
  var patientPos = null;
  var pinningPatient = false;
  var selectedAmb = null;

  function showTab(tab) {
    document.querySelectorAll('.tab').forEach(function(t,i) { t.classList.remove('active'); });
    document.getElementById('tabAmbulances').style.display = tab === 'ambulances' ? 'block' : 'none';
    document.getElementById('tabPending').style.display = tab === 'pending' ? 'block' : 'none';
    event.target.classList.add('active');
  }

  function toast(msg, color) {
    var t = document.getElementById('toast');
    t.innerText = msg;
    t.style.background = color || '#166534';
    t.style.color = color ? '#fff' : '#4ade80';
    t.style.display = 'block';
    setTimeout(function() { t.style.display = 'none'; }, 3000);
  }

  function loadAll() {
    fetch('/ambulances').then(r => r.json()).then(function(ambs) {
      var list = document.getElementById('ambList');
      var sel = document.getElementById('selAmb');
      var pendingList = document.getElementById('pendingList');
      list.innerHTML = '';
      sel.innerHTML = '';
      pendingList.innerHTML = '';
      var pendingCount = 0;

      ambs.forEach(function(a) {
        if (a.status === 'pending') {
          pendingCount++;
          card.innerHTML = '<div class="amb-name">' + (a.driver_name || a.id) + '</div><div class="amb-detail">' + (a.vehicle || '') + '</div><div class="pending-actions"><button class="btn-approve" data-id="' + a.id + '" onclick="approveAmb(this.dataset.id)">Approve</button><button class="btn-reject" data-id="' + a.id + '" onclick="rejectAmb(this.dataset.id)">Reject</button></div>';
          card.innerHTML = '<div class="amb-name">' + (a.driver_name || a.id) + '</div><div class="amb-detail">' + (a.vehicle || '') + '</div><div class="pending-actions"><button class="btn-approve" onclick="approveAmb(\''+a.id+'\')">✓ Approve</button><button class="btn-reject" onclick="rejectAmb(\''+a.id+'\')">✕ Reject</button></div>';
          pendingList.appendChild(card);
          return;
        }

        var card = document.createElement('div');
        card.className = 'amb-card' + (selectedAmb === a.id ? ' selected' : '');
        card.onclick = function() { selectedAmb = a.id; document.getElementById('selAmb').value = a.id; loadAll(); };
        card.innerHTML = '<span class="amb-icon">🚑</span><div class="amb-info"><div class="amb-name">' + (a.driver_name || a.id) + '</div><div class="amb-detail">' + a.id + (a.vehicle ? ' · ' + a.vehicle : '') + '</div></div><span class="amb-status s-' + a.status + '">' + a.status.toUpperCase() + '</span>';
        list.appendChild(card);

        if (a.latitude) {
          if (!ambMarkers[a.id]) {
            var el = document.createElement('div');
            el.innerHTML = '🚑';
            el.style.fontSize = '24px';
            ambMarkers[a.id] = new maplibregl.Marker({element: el}).setLngLat([a.longitude, a.latitude]).setPopup(new maplibregl.Popup().setText(a.driver_name || a.id)).addTo(map);
          } else {
            ambMarkers[a.id].setLngLat([a.longitude, a.latitude]);
          }
        }

        var opt = document.createElement('option');
        opt.value = a.id;
        opt.innerText = (a.driver_name || a.id) + ' (' + a.status + ')';
        sel.appendChild(opt);
      });

      document.getElementById('pendingCount').innerText = pendingCount > 0 ? '(' + pendingCount + ')' : '';
      document.getElementById('statsText').innerText = ambs.filter(a => a.status !== 'pending').length + ' units · ' + ambs.filter(a => a.status === 'dispatched').length + ' active';
    });

    fetch('/hospitals').then(r => r.json()).then(function(hospitals) {
      var sel = document.getElementById('selHospital');
      sel.innerHTML = '';
      hospitals.forEach(function(h) {
        var opt = document.createElement('option');
        opt.value = h.id;
        opt.innerText = h.name;
        sel.appendChild(opt);
      });
    });

    fetch('/traffic-lights').then(r => r.json()).then(function(lights) {
      lights.forEach(function(tl) {
        if (!tlMarkers[tl.id]) {
          var el = document.createElement('div');
          el.innerHTML = '🚦';
          el.style.fontSize = '22px';
          tlMarkers[tl.id] = new maplibregl.Marker({element: el}).setLngLat([tl.longitude, tl.latitude]).setPopup(new maplibregl.Popup().setText(tl.name)).addTo(map);
        }
      });
    });
  }

  function approveAmb(id) {
    fetch('/ambulances/' + id + '/approve', {method: 'POST'}).then(function() {
      toast('Ambulance approved');
      loadAll();
    });
  }

  function rejectAmb(id) {
    fetch('/ambulances/' + id, {method: 'DELETE'}).then(function() {
      toast('Request rejected', '#7f1d1d');
      loadAll();
    });
  }

  function startPatientPin() {
    pinningPatient = true;
    document.getElementById('mapInstruct').style.display = 'block';
  }

  map.on('click', function(e) {
    if (!pinningPatient) return;
    patientPos = e.lngLat;
    if (patientMarker) patientMarker.remove();
    var el = document.createElement('div');
    el.innerHTML = '📍';
    el.style.fontSize = '28px';
    patientMarker = new maplibregl.Marker({element: el}).setLngLat(patientPos).addTo(map);
    document.getElementById('patientInfo').innerText = 'Patient: ' + patientPos.lat.toFixed(5) + ', ' + patientPos.lng.toFixed(5);
    document.getElementById('mapInstruct').style.display = 'none';
    pinningPatient = false;
  });

  function dispatchEmergency() {
    if (!patientPos) { toast('Pin patient location first', '#78350f'); return; }
    var ambId = document.getElementById('selAmb').value;
    var hospitalId = document.getElementById('selHospital').value;
    if (!ambId) { toast('Select an ambulance', '#78350f'); return; }
    fetch('/emergencies', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ambulance_id: ambId, patient_latitude: patientPos.lat, patient_longitude: patientPos.lng, hospital_id: hospitalId})
    }).then(r => r.json()).then(function() {
      toast('Emergency dispatched to ' + ambId);
      patientPos = null;
      if (patientMarker) { patientMarker.remove(); patientMarker = null; }
      document.getElementById('patientInfo').innerText = 'No patient location pinned';
      loadAll();
    });
  }

  var ws = new WebSocket('wss://' + location.host + '/ws/traffic-light');
  ws.onmessage = function(e) {
    var data = JSON.parse(e.data);
    if (data.ambulance) {
      var pos = [data.ambulance.longitude, data.ambulance.latitude];
      if (!ambMarkers[data.ambulance.id]) {
        var el = document.createElement('div');
        el.innerHTML = '🚑';
        el.style.fontSize = '24px';
        ambMarkers[data.ambulance.id] = new maplibregl.Marker({element: el}).setLngLat(pos).addTo(map);
      } else {
        ambMarkers[data.ambulance.id].setLngLat(pos);
      }
    }
  };
  ws.onclose = function() { setTimeout(function() { location.reload(); }, 3000); };

  loadAll();
  setInterval(loadAll, 5000);
</script>
</body>
</html>
"""
    return HTMLResponse(content=html)