import json
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
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

DISCOVERY_MESSAGE = b"CAPSTONE_DISCOVER"
DISCOVERY_PORT = 9999


class AmbulanceTriggerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Ambulance Trigger")
        self.root.geometry("460x560")
        self.root.resizable(False, False)
        self.root.configure(bg="#161b28")

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Header.TLabel", background="#161b28", foreground="#f5f6fb", font=("Segoe UI", 18, "bold"))
        style.configure("Body.TLabel", background="#161b28", foreground="#d7dce8", font=("Segoe UI", 10))
        style.configure("Small.TLabel", background="#161b28", foreground="#9aa4c6", font=("Segoe UI", 9))
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("TEntry", fieldbackground="#252f46", foreground="#f5f6fb")

        self.server = tk.StringVar(value="discover")
        self.ambulance_id = tk.StringVar(value="ambulance-1")
        self.latitude = tk.StringVar(value="40.7123")
        self.longitude = tk.StringVar(value="-74.0065")
        self.interval = tk.DoubleVar(value=2.0)
        self.path_file = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Ready")
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.path_points: List[Dict[str, float]] = DEFAULT_PATH.copy()

        self._build_ui()

    def _build_ui(self) -> None:
        pane = tk.Frame(self.root, bg="#161b28", padx=14, pady=14)
        pane.pack(fill=tk.BOTH, expand=True)

        ttk.Label(pane, text="Ambulance Trigger", style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(pane, text="Auto-discover the server or enter host:port manually.", style="Small.TLabel").pack(anchor=tk.W, pady=(2, 12))

        card = tk.Frame(pane, bg="#1f2640", bd=0)
        card.pack(fill=tk.BOTH, expand=True)
        card.columnconfigure(0, weight=1)

        form = tk.Frame(card, bg="#1f2640")
        form.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        self._add_labeled_entry(form, "Server host:port", self.server)
        self._add_labeled_entry(form, "Ambulance ID", self.ambulance_id)
        self._add_labeled_entry(form, "Latitude", self.latitude)
        self._add_labeled_entry(form, "Longitude", self.longitude)
        self._add_labeled_entry(form, "Interval (seconds)", self.interval)

        path_frame = tk.Frame(card, bg="#1f2640")
        path_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        ttk.Label(path_frame, text="Route path JSON", style="Body.TLabel").pack(anchor=tk.W)
        control = tk.Frame(path_frame, bg="#1f2640")
        control.pack(fill=tk.X, pady=(6, 0))
        ttk.Entry(control, textvariable=self.path_file, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(control, text="Browse", command=self.browse_path).pack(side=tk.LEFT, padx=(10, 0))

        actions = tk.Frame(card, bg="#1f2640")
        actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 0))
        ttk.Button(actions, text="Send Once", command=self.send_once).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(actions, text="Start Route", command=self.start_route).pack(fill=tk.X, pady=(0, 8))
        ttk.Button(actions, text="Stop", command=self.stop_route).pack(fill=tk.X)

        status_frame = tk.Frame(card, bg="#1f2640")
        status_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(12, 16))
        ttk.Label(status_frame, text="Status", style="Body.TLabel").pack(anchor=tk.W)
        status_label = ttk.Label(status_frame, textvariable=self.status_text, style="Body.TLabel", relief=tk.SUNKEN)
        status_label.pack(fill=tk.X, pady=(6, 0))

        log_frame = tk.Frame(card, bg="#1f2640")
        log_frame.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 16))
        log_frame.columnconfigure(0, weight=1)
        ttk.Label(log_frame, text="Activity log", style="Body.TLabel").pack(anchor=tk.W)
        self.log_text = tk.Text(log_frame, height=10, bg="#12182f", fg="#ebeff9", bd=0, padx=10, pady=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.log_text.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _add_labeled_entry(self, parent, label_text, variable):
        frame = tk.Frame(parent, bg="#1f2640")
        frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(frame, text=label_text, style="Body.TLabel").pack(anchor=tk.W)
        entry = ttk.Entry(frame, textvariable=variable)
        entry.pack(fill=tk.X, pady=(6, 0))
        return entry

    def browse_path(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*")],
            title="Open route path JSON",
        )
        if path:
            self.path_file.set(path)
            self.load_path(path)

    def load_path(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as file:
                content = json.load(file)
            if not isinstance(content, list) or any(
                not isinstance(point, dict) or "latitude" not in point or "longitude" not in point
                for point in content
            ):
                raise ValueError("JSON must be a list of objects with latitude and longitude")
            self.path_points = content
            self.log(f"Loaded {len(content)} path points from {path}")
            self.status_text.set("Loaded custom path")
        except Exception as exc:
            messagebox.showerror("Load error", f"Could not load path file:\n{exc}")
            self.path_file.set("")
            self.path_points = DEFAULT_PATH.copy()
            self.status_text.set("Ready")

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

    def send_once(self) -> None:
        point = {
            "latitude": float(self.latitude.get()),
            "longitude": float(self.longitude.get()),
        }
        self._send_point(point)

    def start_route(self) -> None:
        if self.running:
            self.status_text.set("Route already running")
            return
        self.running = True
        self.thread = threading.Thread(target=self._route_loop, daemon=True)
        self.thread.start()
        self.status_text.set("Starting route...")

    def stop_route(self) -> None:
        if not self.running:
            self.status_text.set("Route not running")
            return
        self.running = False
        self.status_text.set("Stopping route...")

    def _route_loop(self) -> None:
        index = 0
        while self.running and index < len(self.path_points):
            point = self.path_points[index]
            self.root.after(0, lambda p=point: self._send_point(p))
            time.sleep(max(0.1, self.interval.get()))
            index += 1
        self.running = False
        if index >= len(self.path_points):
            self.root.after(0, lambda: self.status_text.set("Route finished"))

    def _send_point(self, point: Dict[str, float]) -> None:
        server = self.server.get().strip()
        if not server or server.lower() == "discover":
            discovered = self.discover_server()
            if discovered:
                self.server.set(discovered)
                server = discovered
                self.log(f"Discovered server {discovered}")
                self.status_text.set("Server discovered")
            else:
                self.log("Server discovery failed")
                self.status_text.set("Server not found")
                return

        url = f"http://{server}/ambulance"
        payload = {
            "id": self.ambulance_id.get(),
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        try:
            response = requests.post(url, json=payload, timeout=5)
            response.raise_for_status()
            data = response.json()
            self.log(f"Sent {payload['latitude']}, {payload['longitude']} → {data.get('status')}")
            self.status_text.set(f"Sent update ({data.get('status')})")
        except requests.RequestException as exc:
            self.log(f"Request failed: {exc}")
            self.status_text.set("Error sending update")
            self.running = False

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def on_close(self) -> None:
        self.running = False
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    AmbulanceTriggerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
