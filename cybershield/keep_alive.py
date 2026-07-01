import socket
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

class _PingHandler(BaseHTTPRequestHandler):
    # Explicitly support both GET and HEAD on the root route (/) so
    # uptime monitors like UptimeRobot (which use HEAD requests) don't
    # get a 501 Not Implemented response.
    def do_GET(self):
        self._handle_request(send_body=True)

    def do_HEAD(self):
        self._handle_request(send_body=False)

    def _handle_request(self, send_body: bool):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if send_body:
            self.wfile.write(b"CyberShield is alive.")

    def log_message(self, format, *args):
        pass

class _ReusableServer(HTTPServer):
    allow_reuse_address = True

def keep_alive(port: int = 8099):
    server = _ReusableServer(("0.0.0.0", port), _PingHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
