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
    html_path = Path(__file__).resolve().parent / "navigate.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


def map_page():
    html_path = Path(__file__).resolve().parent / "map.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


@app.get("/hq")
def hq_page():
    html_path = Path(__file__).resolve().parent / "hq.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


@app.get("/map")
def map_page():
    html_path = Path(__file__).resolve().parent / "map.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


class RegisterModel(BaseModel):
    driver_name: str
    vehicle: Optional[str] = None


@app.post("/register")
def register_ambulance(data: RegisterModel):
    new_id = "amb-" + str(uuid.uuid4())[:6]
    new_amb = {"id": new_id, "driver_name": data.driver_name, "vehicle": data.vehicle, "status": "pending"}
    supabase.table("ambulances").insert(new_amb).execute()
    return new_amb


@app.get("/ambulances/{amb_id}")
def get_ambulance(amb_id: str):
    result = supabase.table("ambulances").select("*").eq("id", amb_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Not found")
    return result.data[0]


@app.post("/ambulances/{amb_id}/approve")
def approve_ambulance(amb_id: str):
    supabase.table("ambulances").update({"status": "idle"}).eq("id", amb_id).execute()
    return {"status": "approved"}


@app.delete("/ambulances/{amb_id}")
def delete_ambulance(amb_id: str):
    supabase.table("ambulances").delete().eq("id", amb_id).execute()
    return {"status": "deleted"}

