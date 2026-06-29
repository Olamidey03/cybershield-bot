import socket
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"CyberShield is alive.")

    def log_message(self, format, *args):
        pass

class _ReusableServer(HTTPServer):
    allow_reuse_address = True

def keep_alive(port: int = 8099):
    server = _ReusableServer(("0.0.0.0", port), _PingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
