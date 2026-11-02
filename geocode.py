"""Geocode every participant address (+ Issy) with the Google Geocoding API.

Results are cached in cache/geocode.json keyed by the cleaned address string,
so re-running costs nothing. Use --fallback to geocode with OpenStreetMap
Nominatim instead (free, no key, slower, slightly less accurate) - handy for a
dry run before you set up billing.
"""
import argparse, json, os, sys, time, urllib.parse

import config
import net
from addresses import clean

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "geocode.json")
PARTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "participants.json")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "geocoded.json")

(LAT_MIN, LNG_MIN), (LAT_MAX, LNG_MAX) = config.GEO_BOUNDS


def _get(url):
    return net.get_json(url, timeout=30)


def google(addr, key):
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode(
        {"address": addr, "key": key, "region": "se", "language": "sv",
         "components": "country:SE",
         "bounds": f"{LAT_MIN},{LNG_MIN}|{LAT_MAX},{LNG_MAX}"})
    d = _get(url)
    if d.get("status") != "OK" or not d.get("results"):
        status = d.get("status", "ERROR")
        if d.get("error_message"):
            status = f"{status}: {d['error_message']}"
        return None, status
    r = d["results"][0]
    loc = r["geometry"]["location"]
    return {
        "lat": loc["lat"], "lng": loc["lng"],
        "formatted": r["formatted_address"],
        "location_type": r["geometry"].get("location_type", ""),
        "partial": bool(r.get("partial_match")),
        "source": "google",
    }, "OK"


def nominatim(addr):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": addr, "format": "json", "limit": 1, "countrycodes": "se",
         "viewbox": f"{LNG_MIN},{LAT_MAX},{LNG_MAX},{LAT_MIN}"})
    d = _get(url)
    time.sleep(1.1)  # Nominatim usage policy
    if not d:
        return None, "ZERO_RESULTS"
    r = d[0]
    return {
        "lat": float(r["lat"]), "lng": float(r["lon"]),
        "formatted": r["display_name"], "location_type": r.get("type", ""),
        "partial": False, "source": "nominatim",
    }, "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fallback", action="store_true", help="use Nominatim instead of Google")
    ap.add_argument("--force", action="store_true", help="ignore cache")
    args = ap.parse_args()

    key = config.GOOGLE_SERVER_KEY
    if not args.fallback:
        net.check_key(key, "GOOGLE_API_KEY")

    cache = {} if args.force else (json.load(open(CACHE, encoding="utf-8"))
                                   if os.path.exists(CACHE) else {})
    people = json.load(open(PARTS, encoding="utf-8"))

    targets = [(p["group_id"], clean(p["address_raw"])) for p in people]
    targets.append(("ISSY", config.AFTERPARTY_ADDRESS))

    problems = []
    for gid, addr in targets:
        if addr in cache:
            continue
        res, status = (nominatim(addr) if args.fallback else google(addr, key))
        if res is None:
            problems.append((gid, addr, status))
            print(f"  !! {gid:>4}  {status}  {addr}")
            continue
        cache[addr] = res
        flag = ""
        if not (LAT_MIN <= res["lat"] <= LAT_MAX and LNG_MIN <= res["lng"] <= LNG_MAX):
            flag = "  <-- OUTSIDE STOCKHOLM, CHECK"
            problems.append((gid, addr, "OUT_OF_BOUNDS"))
        if res.get("partial") or res.get("location_type") in ("APPROXIMATE",):
            flag = flag or "  <-- approximate, check"
        print(f"  ok {gid:>4}  {res['lat']:.5f},{res['lng']:.5f}  {res['formatted']}{flag}")

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    out = []
    for p in people:
        addr = clean(p["address_raw"])
        g = cache.get(addr)
        if not g:
            continue
        out.append({**p, "address": addr, "lat": g["lat"], "lng": g["lng"],
                    "formatted": g["formatted"], "geo_flag":
                    ("approx" if g.get("partial") or g.get("location_type") == "APPROXIMATE" else "")})
    issy = cache.get(config.AFTERPARTY_ADDRESS)
    json.dump({"groups": out, "issy": issy}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"\n{len(out)}/{len(people)} groups geocoded -> data/geocoded.json")
    if problems:
        print("\nNEEDS ATTENTION (fix in the sheet or data/address_fixes.json and re-run):")
        for gid, addr, st in problems:
            print(f"  group {gid}: {st}  {addr}")

    ungeocoded = [p["group_id"] for p in people
                  if not cache.get(clean(p["address_raw"]))]
    if ungeocoded or issy is None:
        parts = []
        if ungeocoded:
            parts.append("groups " + ", ".join(str(g) for g in ungeocoded))
        if issy is None:
            parts.append("Issy")
        sys.exit(f"\nGeocoding incomplete ({'; '.join(parts)}). "
                 "Fix the addresses above and re-run before continuing the pipeline.")


if __name__ == "__main__":
    main()
