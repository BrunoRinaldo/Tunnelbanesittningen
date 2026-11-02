"""Configuration for the Tunnelbanesittning planner."""
import os

# ---------------------------------------------------------------- API keys
# Server key: used by geocode.py + travel.py (Geocoding API, Distance Matrix API).
#   -> must NOT have an HTTP-referrer restriction. Restrict by API instead
#      (or by your IP if you have a static one).
# Browser key: used by the web UI (Maps JavaScript API).
#   -> restrict by HTTP referrer to  http://localhost:8000/*  and  http://127.0.0.1:8000/*
# Put them in a file called .env next to this one, or export as env vars.
GOOGLE_SERVER_KEY = os.environ.get("GOOGLE_SERVER_KEY", "")
GOOGLE_BROWSER_KEY = os.environ.get("GOOGLE_BROWSER_KEY", "")

# ---------------------------------------------------------------- event
EVENT_DATE = "2026-11-13"          # YYYY-MM-DD, used for transit departure/arrival times
TIMEZONE = "Europe/Stockholm"

AFTERPARTY_NAME = "Issy"
AFTERPARTY_ADDRESS = "Brinellvägen 23, 114 28 Stockholm, Sweden"

# Arrival deadlines (local time). Travel is costed as "arrive by".
ARRIVE_STARTER = "17:00"           # informational only
ARRIVE_MAIN = "18:45"
ARRIVE_DESSERT = "20:45"
ARRIVE_AFTERPARTY = "22:30"

# Stockholm county. geocode.py prefers matches inside this box and flags any
# result outside it, so widen it if the event ever moves. (lat, lng)
GEO_BOUNDS = ((58.85, 17.25), (59.85, 19.00))

# ---------------------------------------------------------------- messaging (export.py)
# Deadline shown in the "dubbelkolla info" SMS for guests to report errors.
REACHOUT_DATE = "2026-11-08"      # YYYY-MM-DD
# The sheet's Alkoholpreferenser is how many in the pair drink alcohol.
ALCOHOL_BY_COUNT = {"0": "Två alkfri", "1": "En alkfri, en alkfull", "2": "Två alkfull"}
# No stated alcohol preference means the pair wants alcohol - that is the default.
ALCOHOL_DEFAULT = ALCOHOL_BY_COUNT["2"]

# ---------------------------------------------------------------- routing
# Travel cost = min(walking, transit) for each leg.
MODES = ["walking", "transit"]

# travel.py: with free ring membership any pair can end up next to any other, so
# the full 63x63 matrix is fetched. Walking is time-independent (one matrix,
# reused for both inter-home legs); transit is fetched for arrival 18:30 and
# 20:30. Skip the transit call for a pair whose walk is already this short -
# transit can never beat it once waiting time is counted.
TRANSIT_SKIP_MIN = 12

# ---------------------------------------------------------------- solver
SEED = 20261114
# The exact linear layer (linear_sum_assignment, alternated over the rings) now
# does the heavy lifting on the separable part, so the annealing on top - which
# only has to chase the non-linear terms - needs fewer iterations than the old
# pure-anneal search. 1.0M/8 is ~2 min; the old 1.6M was for a weaker search.
ANNEAL_ITERS = 1_000_000
RESTARTS = 16

# --- ring membership -------------------------------------------------------
# Ring is now a decision variable: any pair may land in any ring, but each ring
# still holds exactly 21 pairs. Instead of the hard 21/21/21 split by travel
# time to Issy there is a soft pull:
#     ring_cost = ALPHA * sum_i c[ring(i)] * issy_min(i),   c = (-1, 0, +1)
# so pairs far from Issy are pushed toward the starter ring (ring 0) and pairs
# close to Issy toward the dessert ring (ring 2).
# Measured sweep (haversine data; "outside" = pairs not in the ring their Issy
# rank would give). ring_cost is an absolute magnitude (~ALPHA*350), so a large
# ALPHA swamps the travel terms - keep it a nudge, and read the reported
# violation count as the visible half of the trade-off:
#   ALPHA = 0      -> ring chosen purely for travel time
#   ALPHA ~ 1      -> ~12 outside, mean/tail fully optimised   <- default
#   ALPHA ~ 8      -> ~6 outside, but ring_cost starts dominating, worse max
#   ALPHA ~ 50     -> ~2 outside
#   ALPHA >= 500   -> 0 outside, i.e. exactly the old hard 21/21/21 split
ALPHA = 8.0

# Hard-pin ring 2 (dessert) to the N/3 pairs with the shortest travel time to
# Issy, instead of leaving it as a free decision variable - every dessert
# host is then guaranteed close to the afterparty. Ring 0 vs ring 1
# (starter vs main) stays a free choice, still optimised for travel time
# (with ALPHA's soft pull same as before). This is independent of ALPHA:
# even ALPHA=0 keeps the dessert ring pinned if this is True, and cranking
# ALPHA up no longer forces starter/main into the old hard split too.
LOCK_DESSERT_RING = True

# --- objective (all terms in minutes; std is gone on purpose) -------------
# T_i = leg1 + leg2 + leg3   (starter->main, main->dessert, dessert->Issy)
#   cost = W_MEAN * mean(T)
#        + W_TAIL * sum_i max(0, T_i - T_TARGET)^2
#        + W_MAX  * max(T)
#        + W_LEG  * sum_legs max(0, leg - LEG_CAP)^2
#        + ring_cost
W_MEAN = 1.0
W_TAIL = 0.06
W_MAX = 0.6
W_LEG = 0.10

# Longest single leg before it starts eating the meal (slots are 90/120/90 min).
LEG_CAP = 40.0

# --- host arrival cap ----------------------------------------------------
# A pair that hosts the main or the dessert has to get from the previous
# table home and then cook before the guests arrive. Cap that one arrival
# leg so they have time in the kitchen. The starter host is already home, so
# this only bites ring 1 (arrive from starter) and ring 2 (arrive from main).
#     host_cost = W_HOST * sum_hosts max(0, host_arrival_leg - HOST_ARRIVE_CAP)^2
# W_HOST is deliberately large - this is meant as a near-hard constraint. On
# top of the penalty the annealer refuses any move that raises the number of
# hosts over the cap, and the exact linear layer folds the same term into its
# cost matrix (it is separable there with the other two rings fixed). The
# solver prints "hosts over cap"; that number must be 0 before you send
# anything out - raise W_HOST or re-run with a new SEED if it is not.
HOST_ARRIVE_CAP = 30.0
W_HOST = 8.0

# --- minimum distance between homes --------------------------------------
# Two pairs whose homes are less than this many minutes apart (same address,
# same block) never share a table and no one travels directly between their
# homes. Pairs in the same ring never meet, so neighbours can always be separated
# by ring. Enforced like the host cap: the annealer refuses any move that adds a
# violation, and W_MIN_TRAVEL keeps the exact linear layer from adding one. The
# solver prints the count; it must be 0 before you send anything out. 0 = off.
MIN_TRAVEL_MIN = 5.0
W_MIN_TRAVEL = 1000.0

# T_TARGET is calibrated, not guessed: `python3 solve.py --calibrate` first
# minimises mean(T) alone, then writes T_TARGET = that mean * (1 + SLACK) to
# data/calibration.json. The value below is only the fallback when that file is
# absent.
SLACK = 0.12
T_TARGET = 70.0

# Old objective, kept for the before/after baseline only:
#     mean + W_STD_OLD*std + W_MAX_OLD*max
W_STD_OLD = 2.5
W_MAX_OLD = 0.6

# ---------------------------------------------------------------- server
PORT = 8000

# ---------------------------------------------------------------- SMS (comms page)
# 46elks (https://46elks.se) account used by the comms page to send the SMS
# sendouts and poll delivery status. Leave empty to run the comms page in
# "not configured" mode - sends are logged as skipped instead of going out.
ELKS_API_USERNAME = os.environ.get("ELKS_API_USERNAME", "")
ELKS_API_PASSWORD = os.environ.get("ELKS_API_PASSWORD", "")
# Alphanumeric sender shown to recipients - max 11 GSM characters.
ELKS_FROM = os.environ.get("ELKS_FROM", "TBS")

# Swedish phone number (comms page) that the "Skicka testutskick" button sends
# one real, filled-in copy of every message template to, so you can read them
# on an actual phone before unlocking the real sendouts. Leave empty to hide
# the button.
DOUBLE_CHECK_NUMBER = os.environ.get("DUBBLE_CHECK_TEXTS_TO_NUMBER", "")

# ---------------------------------------------------------------- .env loader
def _load_env():
    global GOOGLE_SERVER_KEY, GOOGLE_BROWSER_KEY
    global ELKS_API_USERNAME, ELKS_API_PASSWORD, ELKS_FROM, DOUBLE_CHECK_NUMBER
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "GOOGLE_SERVER_KEY" and not GOOGLE_SERVER_KEY:
            GOOGLE_SERVER_KEY = v
        elif k == "GOOGLE_BROWSER_KEY" and not GOOGLE_BROWSER_KEY:
            GOOGLE_BROWSER_KEY = v
        elif k == "GOOGLE_API_KEY":
            if not GOOGLE_SERVER_KEY:
                GOOGLE_SERVER_KEY = v
            if not GOOGLE_BROWSER_KEY:
                GOOGLE_BROWSER_KEY = v
        elif k == "ELKS_API_USERNAME" and not ELKS_API_USERNAME:
            ELKS_API_USERNAME = v
        elif k == "ELKS_API_PASSWORD" and not ELKS_API_PASSWORD:
            ELKS_API_PASSWORD = v
        elif k == "ELKS_FROM" and v:
            ELKS_FROM = v
        elif k == "DUBBLE_CHECK_TEXTS_TO_NUMBER" and not DOUBLE_CHECK_NUMBER:
            DOUBLE_CHECK_NUMBER = v

_load_env()
