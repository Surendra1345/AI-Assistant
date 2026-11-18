"""Browser-based 'crystal ring' visualizer: serves a small HTML/CSS/JS page (assistant/webui/)
that draws a ring of crystal shapes rippling like waves, and pushes live mic/speech levels to it
over Server-Sent Events. Opens in the user's default browser.

Replaces the earlier Tkinter attempt: a browser tab is something we can actually verify renders
(unlike a native window spawned from a background process, which turned out unreliable on macOS
and impossible to test from this environment). Every public method is wrapped so a failure here
(port in use, browser won't open, client disconnects) can never crash or block the voice loop.
"""
import json
import logging
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config

log = logging.getLogger("webserver")

WEBUI_DIR = Path(__file__).parent / "webui"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class _Handler(BaseHTTPRequestHandler):
    server: "VisualizerHTTPServer"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _serve_file(self, name: str):
        path = WEBUI_DIR / name
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._serve_file("index.html")
        elif self.path in ("/style.css", "/app.js"):
            self._serve_file(self.path.lstrip("/"))
        elif self.path == "/events":
            self._handle_sse()
        else:
            self.send_error(404)

    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.server.register_client()
        try:
            while True:
                msg = q.get()
                if msg is None:   # server shutting down
                    return
                self.wfile.write(f"data: {msg}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.unregister_client(q)


class VisualizerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._clients: list = []
        self._lock = threading.Lock()

    def register_client(self) -> "queue.Queue":
        q = queue.Queue()
        with self._lock:
            self._clients.append(q)
        return q

    def unregister_client(self, q: "queue.Queue"):
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def broadcast(self, payload: dict):
        msg = json.dumps(payload)
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            q.put_nowait(msg)

    def close_all_clients(self):
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            q.put_nowait(None)


class WebVisualizer:
    """Non-blocking handle, same interface as the old Tkinter Visualizer: start()/set_mode()/
    set_level()/stop(). Every method swallows its own errors so the voice loop never breaks."""

    def __init__(self, port: int = None, open_browser: bool = True):
        self.port = port if port is not None else config.VISUALIZER_PORT
        self._open_browser = open_browser
        self._server = None
        self._thread = None
        self._ok = False

    def start(self):
        try:
            self._server = VisualizerHTTPServer(("127.0.0.1", self.port), _Handler)
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._ok = True
            log.info(f"visualizer serving on http://127.0.0.1:{self.port}/")
            if self._open_browser:
                webbrowser.open(f"http://127.0.0.1:{self.port}/")
        except Exception as e:
            log.warning(f"visualizer unavailable: {e}")
            self._ok = False

    def set_mode(self, mode: str):
        if self._ok:
            try:
                self._server.broadcast({"type": "mode", "value": mode})
            except Exception:
                pass

    def set_level(self, level: float):
        if self._ok:
            try:
                self._server.broadcast({"type": "level", "value": level})
            except Exception:
                pass

    def stop(self):
        if self._ok:
            try:
                self._server.close_all_clients()
                self._server.shutdown()
            except Exception:
                pass
            self._ok = False
