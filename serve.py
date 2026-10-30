"""Serve the map UI at http://localhost:8000

Injects the browser API key at /config.js so the key never lives in a file you
might commit or share.
"""
import http.server, json, os, socketserver, webbrowser

import comms
import config

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/config.js":
            body = ("window.TBS_CONFIG=" + json.dumps({
                "browserKey": config.GOOGLE_BROWSER_KEY,
            }) + ";").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/comms":
            try:
                self._json(comms.sendout_status())
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        routes = {
            "/api/comms/send": lambda p: comms.send_moment(p.get("moment", "")),
            "/api/comms/test-send": lambda p: comms.send_test_all(),
            "/api/comms/status": lambda p: comms.refresh_status(p.get("moment", "")),
            "/api/comms/templates/save": lambda p: comms.save_template(
                p.get("moment", ""), p.get("role_index", -1), p.get("text", "")),
            "/api/comms/templates/reset": lambda p: comms.reset_template(
                p.get("moment", ""), p.get("role_index", -1)),
        }
        if path in routes:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
                self._json(routes[path](payload))
            except ValueError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return
        self._json({"error": "not found"}, 404)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if not os.path.exists(os.path.join(WEB, "data.json")):
        print("web/data.json saknas - kör:  python3 run.py")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", config.PORT), H) as httpd:
        url = f"http://localhost:{config.PORT}/"
        print(f"Tunnelbanesittning -> {url}   (Ctrl+C för att stoppa)")
        if not config.GOOGLE_BROWSER_KEY:
            print("VARNING: GOOGLE_BROWSER_KEY saknas i .env - kartan laddar inte.")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()
