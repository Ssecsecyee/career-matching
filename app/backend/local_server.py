"""Loopback-only local HTTP API; no AWS calls until authenticated chat requests arrive."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal

from src.config import load_local_settings
from src.handlers.dialogue import lambda_handler


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps({"status": "ok", "service": "local_mysql_dialogue"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 60000:
                raise ValueError()
            body = self.rfile.read(length).decode("utf-8")
        except (ValueError, UnicodeError):
            self.send_error(400)
            return
        result = lambda_handler({"headers": dict(self.headers), "body": body}, None)
        self.send_response(result["statusCode"])
        for key, value in result["headers"].items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(result["body"].encode("utf-8"))

    def log_message(self, fmt, *args):
        # Do not log auth tokens or request content.
        pass


if __name__ == "__main__":
    load_local_settings()
    port = int(os.getenv("LOCAL_API_PORT", "8020"))
    if hasattr(signal, "SIGBREAK"):
        def stop_signal(signum, frame):
            raise KeyboardInterrupt()
        signal.signal(signal.SIGBREAK, stop_signal)
    print(f"Local API: http://127.0.0.1:{port} (Ctrl+C to stop)", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

