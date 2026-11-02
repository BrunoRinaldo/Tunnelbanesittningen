"""Show every geocoded pair on a map, with travel time to Issy, and wait for OK.

Opens web/review.html in its own window (Chrome app mode if Chrome is installed,
otherwise a normal browser tab). The script blocks until you press OK; Ctrl+C in
the terminal aborts instead, so a misplaced address can be fixed before the
expensive travel matrix is fetched.

    python3 review_map.py --yes   # fetch missing Issy times from Google (2N elements)
    python3 review_map.py         # no API calls: cached times, else straight-line estimate

The Issy times land in the same cache as travel.py, so that step does not pay for
them again. The map is Leaflet + OpenStreetMap, so it needs no key and works in
--dry; it runs on a free port and can stay up next to serve.py.
"""
import argparse, http.server, json, os, subprocess, sys, threading, webbrowser

import config
import net
import travel

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "web", "review.html")
CHROME = "/Applications/Google Chrome.app"


def build_payload(geo, minutes, modes):
    issy = (geo["issy"]["lat"], geo["issy"]["lng"])
    pairs = []
    for g, m, mo in zip(geo["groups"], minutes, modes):
        pairs.append({
            "id": g["group_id"],
            "names": " & ".join(n for n in (g["name1"], g["name2"]) if n),
            "address": g["formatted"],
            "lat": g["lat"], "lng": g["lng"],
            "approx": bool(g["geo_flag"]),
            "min": round(m, 1),
            "km": round(travel.haversine_km((g["lat"], g["lng"]), issy), 1),
            "mode": mo.rstrip("*"),
            "estimate": mo.endswith("*"),
        })
    return {
        "issy": {"name": config.AFTERPARTY_NAME, "lat": issy[0], "lng": issy[1],
                 "address": geo["issy"]["formatted"]},
        "arrive": config.ARRIVE_AFTERPARTY,
        "pairs": pairs,
    }


def make_handler(payload, confirmed):
    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(open(PAGE, "rb").read(), "text/html; charset=utf-8")
            elif path == "/data.json":
                self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/ok":
                self.send_error(404)
                return
            self._send(b"{}", "application/json")
            confirmed.set()

        def log_message(self, fmt, *args):
            pass

    return H


def open_window(url):
    if sys.platform == "darwin" and os.path.exists(CHROME):
        r = subprocess.run(["open", "-na", CHROME, "--args", f"--app={url}",
                            "--window-size=1280,860"])
        if r.returncode == 0:
            return
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="fetch missing Issy times from Google")
    args = ap.parse_args()

    geo = json.load(open(travel.GEO, encoding="utf-8"))
    pts = [(g["lat"], g["lng"]) for g in geo["groups"]]
    issy = (geo["issy"]["lat"], geo["issy"]["lng"])

    key = config.GOOGLE_SERVER_KEY
    if args.yes:
        net.check_key(key, "GOOGLE_API_KEY")
    cache = json.load(open(travel.CACHE, encoding="utf-8")) if os.path.exists(travel.CACHE) else {}
    minutes, modes = travel.issy_times(pts, issy, key, cache, args.yes)
    if args.yes:
        os.makedirs(os.path.dirname(travel.CACHE), exist_ok=True)
        json.dump(cache, open(travel.CACHE, "w"), indent=0)

    confirmed = threading.Event()
    handler = make_handler(build_payload(geo, minutes, modes), confirmed)
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as httpd:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/"
        print(f"Kartan: {url}")
        print("Väntar på OK i kartfönstret (Ctrl+C för att avbryta) ...")
        open_window(url)
        # wait() with a timeout, so Ctrl+C gets through on every platform
        while not confirmed.wait(0.5):
            pass
        httpd.shutdown()
    print("OK - fortsätter.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nAvbrutet.")
