# Three-Device Ambulance Traffic Light System

This project contains three applications for a three-device system:

- `SERVER` — the central FastAPI server that receives ambulance location updates and pushes status to the traffic-light client
- `PYTHON TRAFFIC LIGHT/PYTHON TRAFFIC LIGHT FRONTEND/traffic_light_frontend.py` — the traffic-light GUI client
- `ambulance_trigger_gui.py` — the ambulance trigger GUI client for desktop route testing
- `ambulance_trigger.py` — a command-line ambulance trigger client

## Improvements included

- improved `/mobile` phone page with manual server address entry
- server status API at `/status`
- root dashboard at `/`
- CORS support for browser-based mobile clients
- enhanced traffic-light GUI with reconnect/discover controls and distance display

## Requirements

Install Python 3.9+ on each device.

## Setup and run the server

1. Open PowerShell.
2. Change directory to the server folder:
   ```powershell
   cd "C:\Users\SAKSHAM\OneDrive\Documents\SUBS\CAPSTONE\SERVER"
   ```
3. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
4. Start the server locally:
   ```powershell
   python -m uvicorn server:app --host 0.0.0.0 --port 8000
   ```

## Run the server with remote access via ngrok

If you want the phone to connect from outside your local network, use ngrok:

1. Install the server dependencies including pyngrok:
   ```powershell
   python -m pip install -r requirements.txt
   ```
2. Run the helper script:
   ```powershell
   python run_with_ngrok.py
   ```
3. Copy the public ngrok URL shown in the terminal.
4. Open that public URL on your phone browser, then go to `/mobile`.

Note: ngrok gives you a temporary public endpoint that forwards traffic to your laptop.

## Cloud deployment (public from anywhere)

For a permanent public server, deploy the `SERVER` app to a cloud container platform.

### Use the provided Dockerfile

The `SERVER/Dockerfile` packages the FastAPI server for cloud deployment.

### Deploy on Render.com, Railway, or another container host

1. Point the platform at the `SERVER` folder or use the root project repository.
2. Make sure the cloud service builds with:
   - `python -m pip install -r requirements.txt`
   - `uvicorn server:app --host 0.0.0.0 --port $PORT`
3. Open the cloud URL in a browser and add `/mobile`.

Example remote mobile URL:

```text
https://<your-cloud-app>.onrender.com/mobile
```

### What changes for the traffic-light client

- the traffic-light client can use the cloud host URL instead of a local LAN IP
- if using the mobile page on a phone, open the cloud app URL and then `/mobile`

### Why this works

- the server becomes reachable from the public internet
- the phone and traffic-light laptop no longer need to share the same local Wi-Fi
- the phone sends GPS updates to the cloud app, and the traffic-light client receives broadcasts from the same cloud app

### Notes

- cloud hosts usually provide a public domain and HTTP/HTTPS access
- for security, avoid publishing the server URL publicly until you want it shared
- if you need an even simpler host, I can add a `Procfile` and a Render/Railway-specific deployment guide next

## Traffic light client (second laptop)

1. Open PowerShell.
2. Go to the frontend folder:
   ```powershell
   cd "C:\Users\SAKSHAM\OneDrive\Documents\SUBS\CAPSTONE\PYTHON TRAFFIC LIGHT\PYTHON TRAFFIC LIGHT FRONTEND"
   ```
3. Install the WebSocket dependency:
   ```powershell
   python -m pip install websocket-client
   ```
4. Run the GUI client:
   ```powershell
   python traffic_light_frontend.py
   ```
5. In the GUI, use `discover` or enter the server host:port directly.
6. Click `Connect`.

## Ambulance trigger client (third device)

### GUI version

1. Open PowerShell.
2. Go to the project root folder:
   ```powershell
   cd "C:\Users\SAKSHAM\OneDrive\Documents\SUBS\CAPSTONE"
   ```
3. Install requests:
   ```powershell
   python -m pip install requests
   ```
4. Run the GUI client:
   ```powershell
   python ambulance_trigger_gui.py
   ```
5. In the GUI, leave the server field as `discover` to auto-find the server, or enter `host:port`.
6. Send a location or start the route.

### Command-line version

```powershell
python ambulance_trigger.py --server discover
```

If you need a manual server address, replace `discover` with `192.168.1.100:8000` or your actual LAN IP.

## Mobile browser live location

1. Make sure the phone is on the same Wi-Fi network as the server laptop.
2. Open the phone browser and visit:
   ```text
   http://<server-ip>:8000/mobile
   ```
   Replace `<server-ip>` with your laptop's local IP address.
3. Allow location access when the browser asks.
4. Optionally enter a custom server address in the page.
5. Tap `Send once` or `Start live updates`.

## Useful server pages

- `/mobile` — phone live sender page
- `/status` — JSON server status
- `/` — basic server dashboard
- `/health` — health check

## Network requirements

- All devices must be on the same local network.
- The phone should be on the same Wi-Fi as the laptop.
- If the phone cannot reach the server, check your local IP and firewall.

## Troubleshooting

If a client cannot connect, verify:

- the server terminal is running
- the server address is correct for the current network
- the phone and laptop are on the same Wi-Fi
- Windows Firewall is not blocking port `8000`
