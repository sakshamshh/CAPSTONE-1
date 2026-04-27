import json
import logging
import math
import socket
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

app = FastAPI(title="Ambulance Radius Server")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure the traffic-light location and triggering radius here.
TRAFFIC_LIGHT_LOCATION = {
    "latitude": 40.7128,
    "longitude": -74.0060,
}
TRIGGER_RADIUS_METERS = 200.0

last_ambulance_update: Optional[Dict[str, object]] = None
last_broadcast: Optional[Dict[str, object]] = None


class AmbulanceLocation(BaseModel):
    id: Optional[str] = "ambulance"
    latitude: float
    longitude: float
    timestamp: Optional[str] = None


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"Traffic-light client connected ({len(self.active_connections)} active)")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logging.info(f"Traffic-light client disconnected ({len(self.active_connections)} active)")

    async def broadcast(self, message: dict) -> None:
        disconnected: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()

DISCOVERY_PORT = 9999
DISCOVERY_MESSAGE = b"CAPSTONE_DISCOVER"
SERVER_PORT = 8000


def start_discovery_server() -> None:
    def discovery_loop() -> None:
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

    thread = threading.Thread(target=discovery_loop, daemon=True)
    thread.start()


start_discovery_server()


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance between two GPS points in meters."""
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def format_timestamp(timestamp: Optional[str] = None) -> str:
    return timestamp or datetime.utcnow().isoformat() + "Z"


def build_status_message(location: AmbulanceLocation) -> dict:
    distance = haversine_distance(
        location.latitude,
        location.longitude,
        TRAFFIC_LIGHT_LOCATION["latitude"],
        TRAFFIC_LIGHT_LOCATION["longitude"],
    )
    triggered = distance <= TRIGGER_RADIUS_METERS

    return {
        "status": "triggered" if triggered else "clear",
        "distance_meters": round(distance, 1),
        "radius_meters": TRIGGER_RADIUS_METERS,
        "traffic_light_location": TRAFFIC_LIGHT_LOCATION,
        "ambulance": {
            "id": location.id or "ambulance",
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timestamp": format_timestamp(location.timestamp),
        },
    }


@app.get("/")
def homepage() -> HTMLResponse:
    html = f"""
    <html>
      <head>
        <title>Ambulance Radius Server</title>
        <style>
          body {{ font-family: Arial, sans-serif; background: #0a1224; color: #eef2ff; margin: 0; padding: 24px; }}
          .card {{ background: #121b36; border-radius: 18px; padding: 24px; max-width: 720px; margin: auto; box-shadow: 0 24px 70px rgba(0,0,0,0.35); }}
          a {{ color: #6fc5ff; text-decoration: none; }}
          code {{ background: rgba(255,255,255,0.08); padding: 4px 8px; border-radius: 6px; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>Ambulance Radius Server</h1>
          <p>Server is running and ready to receive ambulance updates.</p>
          <p><strong>Mobile page:</strong> <a href="/mobile">/mobile</a></p>
          <p><strong>Health check:</strong> <code>/health</code></p>
          <p><strong>Status API:</strong> <code>/status</code></p>
          <p><strong>Last update:</strong> {last_ambulance_update or 'none yet'}</p>
        </div>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/status")
def status_check() -> dict:
    return {
        "status": "ok",
        "active_traffic_light_clients": len(manager.active_connections),
        "last_ambulance_update": last_ambulance_update,
        "last_broadcast": last_broadcast,
        "traffic_light_location": TRAFFIC_LIGHT_LOCATION,
        "trigger_radius_meters": TRIGGER_RADIUS_METERS,
    }


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/ambulance/latest")
def latest_ambulance() -> dict:
    if last_ambulance_update is None:
        raise HTTPException(status_code=404, detail="No ambulance update has been received yet")
    return last_ambulance_update


@app.get("/mobile")
def mobile_sender() -> HTMLResponse:
    html_path = Path(__file__).resolve().parent / "mobile_sender.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"), media_type="text/html")


@app.post("/ambulance")
async def ambulance_update(location: AmbulanceLocation) -> JSONResponse:
    if location.latitude is None or location.longitude is None:
        raise HTTPException(status_code=400, detail="latitude and longitude are required")

    message = build_status_message(location)
    global last_ambulance_update, last_broadcast
    last_ambulance_update = message["ambulance"]
    last_broadcast = message

    logging.info(
        "ambulance update %s → status=%s distance=%s meter(s)",
        last_ambulance_update["id"],
        message["status"],
        message["distance_meters"],
    )

    await manager.broadcast(message)
    return JSONResponse(content=message)


@app.websocket("/ws/traffic-light")
async def traffic_light_ws(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "status": "connected",
                "traffic_light_location": TRAFFIC_LIGHT_LOCATION,
                "radius_meters": TRIGGER_RADIUS_METERS,
            }
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logging.warning("WebSocket error: %s", exc)
        manager.disconnect(websocket)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
