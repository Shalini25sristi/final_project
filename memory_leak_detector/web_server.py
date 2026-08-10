"""Web dashboard backend for the AI Memory Leak & Resource Anomaly Detection platform.

Serves a self-contained HTML/CSS/JS dashboard (in ``web/``) and exposes a small
JSON API that streams live telemetry produced by the same :class:`Monitor`
engine used by the desktop (Tkinter) version. No third-party Python packages
are required.

Run directly::

    python -m memory_leak_detector.web_server --port 8765

Or via the launcher::

    python main.py --web
"""

import argparse
import csv
import datetime as dt
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .monitor import Monitor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

LOG_FIELDS = [
    "timestamp",
    "sample",
    "memory_mb",
    "cpu_percent",
    "risk_score_percent",
    "system_health_percent",
    "threshold_mb",
    "threshold_breached",
    "status",
]

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


class WebDashboard:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, threshold: float = 500.0) -> None:
        self.host = host
        self.port = port
        self.monitor = Monitor()
        self.threshold = threshold
        self.history_limit = 80

        self._lock = threading.Lock()
        self.times = []
        self.memory = []
        self.cpu = []
        self.alerts = []          # [(second, memory_mb), ...] flagged warning points
        self.snapshots = []       # timestamped snapshot records for CSV export

        self.running = True
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample_loop, name="telemetry", daemon=True)
        self._server = None

    # ------------------------------------------------------------ sampling

    def _sample_loop(self) -> None:
        # Warm-up: fill the window so the dashboard is not empty on first paint.
        for _ in range(18):
            self._sample()
        while not self._stop.is_set():
            if self.running:
                self._sample()
            time.sleep(1.0)

    def _sample(self) -> None:
        data = self.monitor.next_data(self.threshold)
        health = max(0, 100 - data.score)
        breached = data.memory_mb > self.threshold

        with self._lock:
            self.times.append(data.second)
            self.memory.append(data.memory_mb)
            self.cpu.append(data.cpu_percent)
            if len(self.times) > self.history_limit:
                self.times.pop(0)
                self.memory.pop(0)
                self.cpu.pop(0)

            if data.leak:
                self.alerts.append((data.second, data.memory_mb))

            self.snapshots.append(
                {
                    "timestamp": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "sample": data.second,
                    "memory_mb": f"{data.memory_mb:.2f}",
                    "cpu_percent": f"{data.cpu_percent:.2f}",
                    "risk_score_percent": data.score,
                    "system_health_percent": health,
                    "threshold_mb": f"{self.threshold:.0f}",
                    "threshold_breached": "YES" if breached else "NO",
                    "status": "WARNING" if data.leak else "STABLE",
                }
            )
            if len(self.snapshots) > 5000:
                self.snapshots = self.snapshots[-5000:]

    # ---------------------------------------------------------------- api

    def snapshot_payload(self) -> dict:
        with self._lock:
            latest = self.snapshots[-1] if self.snapshots else None
            return {
                "running": self.running,
                "backend": self.monitor.backend_text,
                "threshold": self.threshold,
                "sample_count": len(self.snapshots),
                "latest": latest,
                "times": list(self.times),
                "memory": list(self.memory),
                "cpu": list(self.cpu),
                "alerts": list(self.alerts),
                "cpu_max": 100,
            }

    def csv_bytes(self) -> bytes:
        with self._lock:
            rows = list(self.snapshots)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8")

    # ------------------------------------------------------------- server

    def _handler_class(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "AIHealthDashboard/2.0"

            def log_message(self, *_args) -> None:  # keep console clean
                pass

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0].split("#", 1)[0]
                if path == "/api/snapshot":
                    payload = json.dumps(dashboard.snapshot_payload()).encode("utf-8")
                    self._send_bytes(payload, "application/json; charset=utf-8", cache=False)
                elif path == "/api/export.csv":
                    self._send_bytes(
                        dashboard.csv_bytes(),
                        "text/csv; charset=utf-8",
                        filename=f"monitoring_logs_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        cache=False,
                    )
                elif path in ("/", "/index.html"):
                    self._send_file("index.html")
                else:
                    self._send_file(path.lstrip("/"))

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                try:
                    payload = json.loads(body or b"{}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = {}

                if path == "/api/threshold":
                    value = float(payload.get("threshold", dashboard.threshold))
                    if value > 0:
                        dashboard.threshold = value
                    self._send_bytes(
                        json.dumps({"ok": True, "threshold": dashboard.threshold}).encode("utf-8"),
                        "application/json; charset=utf-8",
                        cache=False,
                    )
                elif path == "/api/start":
                    dashboard.running = True
                    self._send_bytes(b'{"ok":true,"running":true}', "application/json; charset=utf-8", cache=False)
                elif path == "/api/stop":
                    dashboard.running = False
                    self._send_bytes(b'{"ok":true,"running":false}', "application/json; charset=utf-8", cache=False)
                else:
                    self._send_bytes(json.dumps({"ok": False}).encode("utf-8"), "application/json; charset=utf-8")

            def _send_file(self, name: str) -> None:
                if not name or ".." in name:
                    self._send_bytes(b"not found", "text/plain", status=404)
                    return
                safe = os.path.normpath(os.path.join(WEB_DIR, name))
                if not safe.startswith(WEB_DIR) or not os.path.isfile(safe):
                    self._send_bytes(b"not found", "text/plain", status=404)
                    return
                ext = os.path.splitext(safe)[1]
                with open(safe, "rb") as handle:
                    self._send_bytes(handle.read(), MIME.get(ext, "application/octet-stream"))

            def _send_bytes(self, data: bytes, content_type: str, cache: bool = True, filename: str = None, status: int = 200) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
                if filename:
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(data)

        return Handler

    def start(self) -> None:
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler_class())
        self._thread.start()

    def serve(self) -> None:
        self.start()
        url = f"http://{self.host}:{self.port}/"
        print("=" * 62)
        print(f"  AI Memory Leak Detection - Web Dashboard")
        print(f"  Backend: {self.monitor.backend_text}")
        print(f"  Open:    {url}")
        print("=" * 62)
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            self._server.server_close()


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the AI Memory Leak web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--threshold", type=float, default=500.0)
    args = parser.parse_args(argv)

    WebDashboard(host=args.host, port=args.port, threshold=args.threshold).serve()


if __name__ == "__main__":
    main()
