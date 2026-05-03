import json
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional
from xmlrpc import server

import websocket

DISCOVERY_MESSAGE = b"CAPSTONE_DISCOVER"
DISCOVERY_PORT = 9999


class TrafficLightApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Traffic Light Client")
        self.root.state("zoomed")
        self.root.resizable(False, False)
        self.root.configure(bg="#1f2330")

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Header.TLabel", background="#1f2330", foreground="#f5f6fb", font=("Segoe UI", 16, "bold"))
        style.configure("Body.TLabel", background="#1f2330", foreground="#d9dce6", font=("Segoe UI", 10))
        style.configure("Small.TLabel", background="#1f2330", foreground="#a8b0d0", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("TEntry", fieldbackground="#2f3450", foreground="#f5f6fb")

        self.ws_app: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.status = tk.StringVar(value="disconnected")
        self.traffic_status = tk.StringVar(value="waiting for data")
        self.distance_text = tk.StringVar(value="—")
        self.server_address = tk.StringVar(value="discover")
        self.last_update = tk.StringVar(value="No messages yet")
        self.light_state = "clear"

        self._build_ui()

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, bg="#1f2330", padx=14, pady=14)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Traffic Light", style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(container, text="Auto-discover the server or enter a host:port.", style="Small.TLabel").pack(anchor=tk.W, pady=(0, 10))

        card = tk.Frame(container, bg="#242b44", bd=0, highlightthickness=0)
        card.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)

        server_frame = tk.Frame(card, bg="#242b44")
        server_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        ttk.Label(server_frame, text="Server host:port", style="Body.TLabel").pack(anchor=tk.W)
        self.server_entry = ttk.Entry(server_frame, textvariable=self.server_address)
        self.server_entry.pack(fill=tk.X, pady=(6, 0))

        controls = tk.Frame(server_frame, bg="#242b44")
        controls.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(controls, text="Connect", command=self.start_connection).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(controls, text="Discover", command=self.discover_and_connect).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        ttk.Button(controls, text="Disconnect", command=self.stop_connection).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        info_frame = tk.Frame(card, bg="#242b44")
        info_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        ttk.Label(info_frame, text="Connection status", style="Body.TLabel").pack(anchor=tk.W)
        ttk.Label(info_frame, textvariable=self.status, style="Body.TLabel").pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(info_frame, text="Light state", style="Body.TLabel").pack(anchor=tk.W, pady=(10, 0))
        ttk.Label(info_frame, textvariable=self.traffic_status, style="Body.TLabel").pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(info_frame, text="Distance", style="Body.TLabel").pack(anchor=tk.W, pady=(10, 0))
        ttk.Label(info_frame, textvariable=self.distance_text, style="Small.TLabel").pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(info_frame, text="Last message", style="Body.TLabel").pack(anchor=tk.W, pady=(10, 0))
        ttk.Label(info_frame, textvariable=self.last_update, style="Small.TLabel").pack(anchor=tk.W, pady=(4, 0))

        self.canvas = tk.Canvas(card, width=260, height=340, bg="#151820", highlightthickness=0)
        self.canvas.grid(row=2, column=0, padx=12, pady=(0, 12))

        self.circle_ids = {
            "red": self.canvas.create_oval(40, 20, 220, 120, fill="#440000", outline="#661111", width=4),
            "yellow": self.canvas.create_oval(40, 130, 220, 230, fill="#544400", outline="#666611", width=4),
            "green": self.canvas.create_oval(40, 240, 220, 340, fill="#004400", outline="#116611", width=4),
        }

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def start_connection(self) -> None:
        if self.ws_thread and self.ws_thread.is_alive():
            return

        self.stop_event.clear()
        self.status.set("connecting...")
        self.set_traffic_light("disconnected")
        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()

    def set_traffic_light(self, state: str) -> None:
        self.light_state = state
        if state == "triggered":
            colors = {"red": "#550000", "yellow": "#6c6c00", "green": "#00d000"}
            self.traffic_status.set("TRIGGERED")
        elif state == "clear":
            colors = {"red": "#ff3d3d", "yellow": "#bfbf00", "green": "#004400"}
            self.traffic_status.set("CLEAR")
        elif state == "connected":
            colors = {"red": "#440000", "yellow": "#444400", "green": "#004400"}
            self.traffic_status.set("CONNECTED")
        else:
            colors = {"red": "#440000", "yellow": "#444400", "green": "#004400"}
            self.traffic_status.set("DISCONNECTED")

        for key, circle_id in self.circle_ids.items():
            self.canvas.itemconfig(circle_id, fill=colors[key])

    def stop_connection(self) -> None:
        self.stop_event.set()
        if self.ws_app:
            try:
                self.ws_app.close()
            except Exception:
                pass
        self.status.set("disconnected")
        self.set_traffic_light("disconnected")

    def discover_and_connect(self) -> None:
        if self.ws_thread and self.ws_thread.is_alive():
            return
        self.server_address.set("discover")
        self.start_connection()

    def discover_server(self, timeout: float = 3.0) -> Optional[str]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", DISCOVERY_PORT))
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

    def _run_websocket(self) -> None:
        while not self.stop_event.is_set():
            server = self.server_address.get().strip()
            if not server:
                self.root.after(0, lambda: self.status.set("invalid server address"))
                return

            if server.lower() == "discover":
                self.root.after(0, lambda: self.status.set("discovering server..."))
                discovered = self.discover_server()
                if discovered:
                    server = discovered
                    self.root.after(0, lambda: self.server_address.set(discovered))
                    self.root.after(0, lambda: self.status.set(f"discovered {discovered}"))
                else:
                    self.root.after(0, lambda: self.status.set("server not found"))
                    time.sleep(3)
                    continue

            url = f"wss://{server}/ws/traffic-light" if "onrender.com" in server else f"ws://{server}/ws/traffic-light"
            def on_open(ws: websocket.WebSocketApp) -> None:
                self.root.after(0, lambda: self.status.set("connected"))

            def on_message(ws: websocket.WebSocketApp, message: str) -> None:
                try:
                    payload = json.loads(message)
                    state = payload.get("status", "clear")
                    distance = payload.get('distance_meters', '?')
                    self.root.after(0, lambda: self.status.set(f"{state} ({distance}m)"))
                    amb = payload.get("ambulance", {})
                    amb_info = f"{distance} m  |  lat {amb.get('latitude','?')}  lon {amb.get('longitude','?')}  id {amb.get('id','?')}"
                    self.root.after(0, lambda i=amb_info: self.distance_text.set(i))
                    self.root.after(0, lambda: self.last_update.set(json.dumps(payload)))
                    self.root.after(0, lambda: self.set_traffic_light(state))
                except json.JSONDecodeError:
                    self.root.after(0, lambda: self.status.set("received invalid message"))

            def on_close(ws: websocket.WebSocketApp, close_status_code, close_msg) -> None:
                if not self.stop_event.is_set():
                    self.root.after(0, lambda: self.status.set("disconnected"))
                    self.root.after(0, lambda: self.distance_text.set("—"))
                    self.root.after(0, lambda: self.set_traffic_light("disconnected"))

            def on_error(ws: websocket.WebSocketApp, error: Exception) -> None:
                self.root.after(0, lambda: self.status.set(f"error: {error}"))

            try:
                self.ws_app = websocket.WebSocketApp(
                    url,
                    on_open=on_open,
                    on_message=on_message,
                    on_close=on_close,
                    on_error=on_error,
                )
                self.ws_app.run_forever(ping_interval=10, ping_timeout=5)
            except Exception:
                self.root.after(0, lambda: self.status.set("retrying after error"))
                time.sleep(2)
            finally:
                if not self.stop_event.is_set():
                    self.root.after(0, lambda: self.status.set("reconnecting..."))
                    time.sleep(1)

    def on_close(self) -> None:
        self.stop_event.set()
        if self.ws_app:
            try:
                self.ws_app.close()
            except Exception:
                pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = TrafficLightApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
