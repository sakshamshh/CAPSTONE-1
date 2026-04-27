# Ambulance Radius Server

This server receives ambulance location updates and notifies the traffic-light client when the ambulance enters the trigger radius.

## Setup

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the server

From inside the `SERVER` folder:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Then use the server laptop IP address from other devices. For example:

```text
172.16.38.68:8000
```

Or from the project root:

```bash
cd SERVER
uvicorn server:app --host 0.0.0.0 --port 8000
```

## Endpoints

- `POST /ambulance`
  - Body example:
    ```json
    {
      "id": "ambulance-1",
      "latitude": 40.713,
      "longitude": -74.0062,
      "timestamp": "2026-04-24T12:00:00Z"
    }
    ```
- `GET /config`
  - Returns configured traffic light location and trigger radius.
- `GET /health`
  - Returns `{"status": "ok"}`.
- `WebSocket /ws/traffic-light`
  - Traffic-light client connects here and receives trigger messages.
- `GET /mobile`
  - Opens a phone-friendly page for live GPS updates.

## Discovery

This server also listens for local UDP discovery on port `9999`. The Python clients can use `discover` to auto-find the server after a network change.

## Usage

- The ambulance phone sends location updates to `/ambulance`.
- The server computes the distance to the traffic light location.
- If the ambulance is inside the configured radius, the server broadcasts `{"status": "triggered"}` to connected traffic-light clients.
- Otherwise, it broadcasts `{"status": "clear"}`.

## Notes

- Update `TRAFFIC_LIGHT_LOCATION` and `TRIGGER_RADIUS_METERS` in `server.py` to match your real deployment.
- Use the server laptop IP address on the local network for both the ambulance phone and the traffic-light laptop.
