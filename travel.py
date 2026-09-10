"""Build the travel-time matrices with the Google Distance Matrix API.

For every leg we take min(walking, transit), with transit costed as "arrive by"
the deadline in config.py. Everything is cached in cache/travel.json keyed by
(origin, destination, mode, arrival) so re-runs are free.

Ring membership is now a solver decision variable, so any pair can end up next
to any other pair and the FULL NxN matrix is needed (N = pair count, 63 for this
event):

    walking            one NxN matrix, time-independent, reused for both
                       inter-home legs
    transit  18:30     NxN, arrival = ARRIVE_MAIN   (leg starter -> main)
    transit  20:30     NxN, arrival = ARRIVE_DESSERT (leg main -> dessert)
    everyone -> Issy   N elements, arrival = ARRIVE_AFTERPARTY (leg 3)

Pruning: the transit call is skipped for any pair whose walk time is already
<= TRANSIT_SKIP_MIN (config.py, default 12 min). Transit cannot beat that once
the wait is counted, so min(walk, transit) = walk there anyway.

The element count and an estimated dollar cost are printed BEFORE any call is
made; actually spending requires the --yes flag.

--haversine skips the API entirely and estimates from straight-line distance
(walk 4.8 km/h; transit 21 km/h + 9 min overhead). Good enough to test the
pipeline, not good enough to send to 126 people.
"""
import argparse, datetime, json, math, os, sys, time, urllib.parse
from zoneinfo import ZoneInfo

import config
import net

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache", "travel.json")
GEO = os.path.join(HERE, "data", "geocoded.json")
OUT = os.path.join(HERE, "data", "travel.json")

WALK_KMH = 4.8
TRANSIT_KMH = 21.0
TRANSIT_OVERHEAD_MIN = 9.0
DETOUR = 1.28  # street-network detour factor vs great-circle

# Google Distance Matrix: ~USD 5 per 1000 elements on the standard tier.
USD_PER_1000_ELEMENTS = 5.0


def ts(hhmm):
    d = datetime.datetime.strptime(f"{config.EVENT_DATE} {hhmm}", "%Y-%m-%d %H:%M")
    return int(d.replace(tzinfo=ZoneInfo(config.TIMEZONE)).timestamp())


def haversine_km(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def est(a, b):
    km = haversine_km(a, b) * DETOUR
    walk = km / WALK_KMH * 60
    transit = km / TRANSIT_KMH * 60 + TRANSIT_OVERHEAD_MIN
    return min(walk, transit), ("walking" if walk <= transit else "transit"), km


def ckey(o, d, mode, arrival):
    a = arrival if mode == "transit" else 0
    return f"{o[0]:.5f},{o[1]:.5f}|{d[0]:.5f},{d[1]:.5f}|{mode}|{a}"


def dm_call(origins, dests, mode, arrival, key):
    params = {
        "origins": "|".join(f"{o[0]},{o[1]}" for o in origins),
        "destinations": "|".join(f"{d[0]},{d[1]}" for d in dests),
        "mode": mode, "language": "sv", "region": "se", "units": "metric", "key": key,
    }
    if mode == "transit":
        params["arrival_time"] = arrival
    url = "https://maps.googleapis.com/maps/api/distancematrix/json?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        d = net.get_json(url, timeout=60)
        if d.get("status") == "OK":
            return d
        if d.get("status") in ("OVER_QUERY_LIMIT", "UNKNOWN_ERROR"):
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"Distance Matrix: {d.get('status')} {d.get('error_message','')}")
    raise RuntimeError("Distance Matrix: retries exhausted")


def needed_pairs(pa, pb, mode, arrival, cache, skip=None):
    """(i, j) index pairs whose value is not cached and not pruned/self."""
    out = []
    for i, o in enumerate(pa):
        for j, d in enumerate(pb):
            if skip is not None and skip(i, j):
                continue
            if ckey(o, d, mode, arrival) not in cache:
                out.append((i, j))
    return out


def fetch_mode(pa, pb, mode, arrival, key, cache, label, skip=None, spend=False):
    """Fill cache for the (mode, arrival) block, then return minutes[i][j] / None."""
    n, m = len(pa), len(pb)
    need = needed_pairs(pa, pb, mode, arrival, cache, skip)
    if need and spend:
        want = {}
        for i, j in need:
            want.setdefault(i, set()).add(j)
        # Google caps at 25 dests / 100 elements / request.
        CHUNK_O, CHUNK_D = 4, 25
        rows = sorted(want)
        for r0 in range(0, len(rows), CHUNK_O):
            ors = rows[r0:r0 + CHUNK_O]
            cols = sorted(set().union(*(want[i] for i in ors)))
            for c0 in range(0, len(cols), CHUNK_D):
                ocs = cols[c0:c0 + CHUNK_D]
                oa = [pa[i] for i in ors]
                ob = [pb[j] for j in ocs]
                res = dm_call(oa, ob, mode, arrival, key)
                for ii, row in enumerate(res["rows"]):
                    for jj, el in enumerate(row["elements"]):
                        k = ckey(pa[ors[ii]], pb[ocs[jj]], mode, arrival)
                        cache[k] = el["duration"]["value"] / 60.0 if el.get("status") == "OK" else None
                print(f"    {label}: fetched {len(oa)}x{len(ob)}")
    elif need:
        print(f"    {label}: {len(need)} elements NOT fetched (no --yes)")

    grid = [[None] * m for _ in range(n)]
    for i, o in enumerate(pa):
        for j, d in enumerate(pb):
            if skip is not None and skip(i, j):
                continue
            grid[i][j] = cache.get(ckey(o, d, mode, arrival))
    return grid


def combine(walk, transit):
    """min(walk, transit) per cell, plus the winning mode ('' where both None)."""
    n, m = len(walk), len(walk[0])
    best = [[None] * m for _ in range(n)]
    mode = [[""] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            w, t = walk[i][j], transit[i][j]
            cand = [(w, "walking"), (t, "transit")]
            cand = [(v, mo) for v, mo in cand if v is not None]
            if cand:
                v, mo = min(cand)
                best[i][j], mode[i][j] = v, mo
    return best, mode


def fill_holes(best, mode, pts_a, pts_b):
    """Any cell still None (no route by either mode, self-pair excluded) -> estimate."""
    for i in range(len(best)):
        for j in range(len(best[0])):
            if i < len(pts_a) and j < len(pts_b) and pts_a[i] == pts_b[j]:
                best[i][j], mode[i][j] = 0.0, "self"
                continue
            if best[i][j] is None:
                e, mo, _ = est(pts_a[i], pts_b[j])
                best[i][j], mode[i][j] = e, mo + "*"


def haversine_payload(pts, issy, ids):
    N = len(pts)
    walk = [[est(a, b)[0] for b in pts] for a in pts]
    wmode = [[est(a, b)[1] for b in pts] for a in pts]
    for i in range(N):
        walk[i][i], wmode[i][i] = 0.0, "self"
    to_issy = [est(p, issy)[0] for p in pts]
    return {
        "ids": ids, "source": "haversine",
        "walk": walk, "walk_mode": wmode,
        "t1": walk, "mode1": wmode,          # time-independent estimate
        "t2": walk, "mode2": wmode,
        "to_issy": to_issy, "to_issy_mode": [est(p, issy)[1] for p in pts],
        # legacy aliases
        "full": walk, "modes": wmode,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--haversine", action="store_true", help="no API, straight-line estimate")
    ap.add_argument("--yes", action="store_true", help="actually spend money on the API calls")
    args = ap.parse_args()

    geo = json.load(open(GEO, encoding="utf-8"))
    groups = geo["groups"]
    issy = (geo["issy"]["lat"], geo["issy"]["lng"])
    pts = [(g["lat"], g["lng"]) for g in groups]
    ids = [g["group_id"] for g in groups]
    N = len(pts)

    if args.haversine:
        json.dump(haversine_payload(pts, issy, ids), open(OUT, "w"), indent=0)
        print(f"haversine matrix written ({N}x{N}) -> data/travel.json")
        return

    key = config.GOOGLE_SERVER_KEY
    net.check_key(key, "GOOGLE_API_KEY")
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    arr_main, arr_dess, arr_issy = ts(config.ARRIVE_MAIN), ts(config.ARRIVE_DESSERT), ts(config.ARRIVE_AFTERPARTY)

    # ---- walking, time-independent (cache bucket 0), whole matrix -----------
    self_pair = lambda i, j: pts[i] == pts[j]
    walk_need = needed_pairs(pts, pts, "walking", 0, cache, self_pair)

    # ---- transit pruning: skip pairs whose (cached-or-just-planned) walk is
    #      already <= TRANSIT_SKIP_MIN. Unknown walk -> do not prune.
    def walk_cached(i, j):
        return cache.get(ckey(pts[i], pts[j], "walking", 0))

    def transit_skip(i, j):
        """Prune once the real walk time is known (during the actual fetch)."""
        if pts[i] == pts[j]:
            return True
        w = walk_cached(i, j)
        return w is not None and w <= config.TRANSIT_SKIP_MIN

    def transit_skip_est(i, j):
        """Planning-time prune: use the haversine walk when the real one is not
        cached yet, so the printed estimate is not wildly high."""
        if transit_skip(i, j):
            return True
        if walk_cached(i, j) is not None:
            return False
        wkm = haversine_km(pts[i], pts[j]) * DETOUR
        return wkm / WALK_KMH * 60 <= config.TRANSIT_SKIP_MIN

    tr_main_hi = needed_pairs(pts, pts, "transit", arr_main, cache, transit_skip)
    tr_dess_hi = needed_pairs(pts, pts, "transit", arr_dess, cache, transit_skip)
    tr_main_need = needed_pairs(pts, pts, "transit", arr_main, cache, transit_skip_est)
    tr_dess_need = needed_pairs(pts, pts, "transit", arr_dess, cache, transit_skip_est)
    issy_need = needed_pairs(pts, [issy], "walking", 0, cache) + \
        needed_pairs(pts, [issy], "transit", arr_issy, cache)

    total = len(walk_need) + len(tr_main_need) + len(tr_dess_need) + len(issy_need)
    total_hi = len(walk_need) + len(tr_main_hi) + len(tr_dess_hi) + len(issy_need)
    est_usd = total / 1000.0 * USD_PER_1000_ELEMENTS
    n = len(pts)
    print(f"Full {n}x{n} travel matrix - elements to fetch (not already cached):")
    print(f"    walking {n}x{n}              {len(walk_need):5d}")
    print(f"    transit {n}x{n} @ {config.ARRIVE_MAIN}       {len(tr_main_need):5d}  (est. after walk <= {config.TRANSIT_SKIP_MIN} min pruning)")
    print(f"    transit {n}x{n} @ {config.ARRIVE_DESSERT}       {len(tr_dess_need):5d}  (same pruning)")
    print(f"    everyone -> Issy           {len(issy_need):5d}")
    print(f"    -------------------------------")
    print(f"    total (estimate)           {total:5d}   ~ USD {est_usd:.2f}")
    print(f"    total (upper bound)        {total_hi:5d}   ~ USD {total_hi / 1000.0 * USD_PER_1000_ELEMENTS:.2f}")

    if total == 0:
        print("\nEverything is already cached - nothing to spend.")
    elif not args.yes:
        print("\nThis would spend money. Re-run with --yes to actually fetch:")
        print("    python3 travel.py --yes")
        sys.exit(0)

    spend = args.yes and total > 0

    print("\nWalking (time-independent, both inter-home legs) ...")
    walk = fetch_mode(pts, pts, "walking", 0, key, cache, "walk", self_pair, spend)

    print(f"Transit @ {config.ARRIVE_MAIN} (starter -> main) ...")
    tr_main = fetch_mode(pts, pts, "transit", arr_main, key, cache, "transit@main", transit_skip, spend)
    print(f"Transit @ {config.ARRIVE_DESSERT} (main -> dessert) ...")
    tr_dess = fetch_mode(pts, pts, "transit", arr_dess, key, cache, "transit@dessert", transit_skip, spend)

    print("Leg 3 (everyone -> Issy, arrive 22:00) ...")
    iw = fetch_mode(pts, [issy], "walking", 0, key, cache, "->Issy walk", None, spend)
    it = fetch_mode(pts, [issy], "transit", arr_issy, key, cache, "->Issy transit", None, spend)

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, "w"), indent=0)

    walk_mode = [["walking" if v is not None else "" for v in row] for row in walk]
    fill_holes(walk, walk_mode, pts, pts)

    t1, mode1 = combine(walk, tr_main)
    t2, mode2 = combine(walk, tr_dess)
    fill_holes(t1, mode1, pts, pts)
    fill_holes(t2, mode2, pts, pts)

    issy_best, issy_mode = combine(iw, it)
    for i in range(N):
        if issy_best[i][0] is None:
            e, mo, _ = est(pts[i], issy)
            issy_best[i][0], issy_mode[i][0] = e, mo + "*"
    to_issy = [r[0] for r in issy_best]
    to_issy_mode = [r[0] for r in issy_mode]

    payload = {
        "ids": ids, "source": "google",
        "walk": walk, "walk_mode": walk_mode,
        "t1": t1, "mode1": mode1,
        "t2": t2, "mode2": mode2,
        "to_issy": to_issy, "to_issy_mode": to_issy_mode,
        # legacy aliases (leg1 view) for anything still reading the old keys
        "full": t1, "modes": mode1,
    }
    json.dump(payload, open(OUT, "w"), indent=0)
    fetched = sum(1 for r in t1 for v in r if v is not None)
    print(f"\nwritten -> data/travel.json  (full {N}x{N}, {fetched} leg-1 cells)")


if __name__ == "__main__":
    main()
