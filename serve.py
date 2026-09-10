"""Serve the map UI at http://localhost:8000

Injects the browser API key at /config.js so the key never lives in a file you
might commit or share.
"""
import http.server, json, os, socketserver, webbrowser

import config

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def do_GET(self):
        if self.path.split("?")[0] == "/config.js":
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
        return super().do_GET()

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
