import argparse
import json
import socket
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import requests


DEFAULT_PATH: List[Dict[str, float]] = [
    {"latitude": 40.7123, "longitude": -74.0065},
    {"latitude": 40.7125, "longitude": -74.0064},
    {"latitude": 40.7127, "longitude": -74.0062},
    {"latitude": 40.7129, "longitude": -74.0061},
    {"latitude": 40.7131, "longitude": -74.0060},
    {"latitude": 40.7133, "longitude": -74.0058},
]


def discover_server(timeout: float = 3.0) -> Optional[str]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(b"CAPSTONE_DISCOVER", ("255.255.255.255", 9999))
        data, _ = sock.recvfrom(1024)
        payload = json.loads(data.decode("utf-8"))
        return f"{payload['host']}:{payload['port']}"
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def send_update(server: str, location: Dict[str, float], ambulance_id: str) -> Optional[dict]:
    url = f"http://{server}/ambulance"
    payload = {
        "id": ambulance_id,
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    response = requests.post(url, json=payload, timeout=5)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ambulance trigger client for the traffic-light server."
    )
    parser.add_argument(
        "--server",
        default="discover",
        help="Server host:port or 'discover' to auto-find local server",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between location updates (default: 2.0)",
    )
    parser.add_argument(
        "--ambulance-id",
        default="ambulance-1",
        help="Ambulance identifier string",
    )
    parser.add_argument(
        "--path",
        help="Optional JSON file with a list of {latitude, longitude} points",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Send a single location update and exit",
    )
    args = parser.parse_args()

    if args.path:
        try:
            with open(args.path, "r", encoding="utf-8") as file:
                path = json.load(file)
            if not isinstance(path, list):
                raise ValueError("Path JSON must be a list of coordinate objects")
        except Exception as exc:
            print(f"Failed to load path file: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        path = DEFAULT_PATH

    if not args.server or args.server.lower() == "discover":
        discovered = discover_server()
        if discovered:
            args.server = discovered
            print(f"Discovered server at http://{discovered}")
        else:
            print("Failed to discover the server on the local network.", file=sys.stderr)
            sys.exit(1)

    print(f"Starting ambulance trigger client against http://{args.server}")
    print(f"Ambulance ID: {args.ambulance_id}")
    print(f"Update interval: {args.interval}s")
    print(f"Send once: {args.once}")

    for index, point in enumerate(path):
        try:
            payload = send_update(args.server, point, args.ambulance_id)
            print(
                f"[{index + 1}/{len(path)}] sent {point['latitude']}, {point['longitude']} ->",
                payload,
            )
        except Exception as exc:
            print(f"Error sending update: {exc}", file=sys.stderr)

        if args.once:
            break

        if index < len(path) - 1:
            time.sleep(args.interval)

    print("Finished sending ambulance updates.")


if __name__ == "__main__":
    main()
