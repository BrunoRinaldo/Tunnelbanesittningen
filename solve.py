"""Build the Tunnelbanesittning schedule.

Design
------
N pairs (this event: 63), three courses, N/3 tables per course, 3 pairs per
table, every pair hosts exactly once. "No pair meets twice" is not left to a
heuristic - it is guaranteed by construction. N must be an odd multiple of 3
(3, 9, 15, 21, ..., 63, 69, ...); set_ring_size() derives the ring size R = N/3
from the pair count and main() rejects any other N.

Split the N pairs into three rings of R. Ring 0 hosts the starter, ring 1 the
main, ring 2 the dessert. Which pair lands in which ring is a DECISION
VARIABLE (each ring still holds exactly R), nudged by a soft pull, ring_cost
in config.py. With config.LOCK_DESSERT_RING (default True), ring 2 is
additionally hard-pinned to the R pairs closest to Issy - every dessert host
is then guaranteed a short last leg - while ring 0 vs ring 1 stays free and
is still optimised for travel time.

Label the pairs in ring k as pk[0..R-1], indices in Z_R. For round
r in {0=starter, 1=main, 2=dessert} the tables are

    B_r(x) = { p0[x], p1[x+r], p2[2x+r] }          x in Z_R

This is a parallel class of the transversal design built on the Cayley table
of Z_R. R odd => 2 is invertible mod R => 2x+r is a bijection; an even R would
let two pairs meet twice, which is why main() requires R odd. Two pairs from
different rings share a table iff a single congruence holds:

    p0[x] & p1[y] : r = y - x        p0[x] & p2[z] : r = z - 2x
    p1[y] & p2[z] : r = 2y - z

Each has exactly one solution in Z_R, and only r in {0,1,2} is played, so any
two pairs meet at most once. Pairs inside the same ring never share a table at
all. Zero repeats, provably, for every permutation p0/p1/p2 and every ring
assignment. solve.py also verifies the result brute force before writing it.

Search
------
This is a quadratic assignment problem over N seats (seat = ring + index), so
the exact optimum is out of reach. Three layers:

 1. With two rings fixed, the sum-of-travel objective is a plain linear
    assignment over the third ring (no travel term couples two members of the
    same ring), solved exactly with scipy.optimize.linear_sum_assignment.
    Alternated over the rings until it stops improving.
 2. Simulated annealing on top for the non-linear terms (tail^2, max, per-leg
    cap^2, host-arrival cap^2). Move set: swap two labels inside a ring, OR
    swap two pairs BETWEEN rings (which changes who hosts what). The anneal
    also refuses any move that raises the count of hosts whose arrival leg to
    their own course exceeds HOST_ARRIVE_CAP, so that near-hard constraint is
    driven to zero and then kept there.
 3. Multi-restart, SEED in config.py, so runs reproduce.

Homes closer than MIN_TRAVEL_MIN are kept apart the same way: neither at one
table nor as the two ends of a leg. Every such term couples two different rings,
so it is separable in the exact layer too, and the anneal refuses moves adding one.

The host-arrival term (W_HOST * sum max(0, arrival_leg - HOST_ARRIVE_CAP)^2)
is separable once the other two rings are fixed - the main host's arrival
depends only on which pair sits beside them in ring 0, the dessert host's only
on ring 1 - so it is folded into the exact linear layer's cost matrix too.

--calibrate first minimises mean(T) alone, then writes
T_TARGET = that mean * (1 + SLACK) to data/calibration.json.
"""
import argparse, json, math, os, sys

import numpy as np
from scipy.optimize import linear_sum_assignment

import config

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(HERE, "data", "geocoded.json")
TRV = os.path.join(HERE, "data", "travel.json")
OUT = os.path.join(HERE, "data", "schedule.json")
CALIB = os.path.join(HERE, "data", "calibration.json")
BASELINE = os.path.join(HERE, "data", "baseline.json")

N_RING = 21   # pairs per ring; overwritten from the participant count in main()
COURSES = ["starter", "main", "dessert"]
SV = {"starter": "Förrätt", "main": "Varmrätt", "dessert": "Efterrätt"}
INV2 = 11     # inverse of 2 mod N_RING (2*11 = 22 = 1 mod 21); reset in main()
RING_C = (-1.0, 0.0, 1.0)  # ring_cost coefficient per ring


def set_ring_size(n_pairs):
    """Derive the per-ring size (and the mod-N_RING inverse of 2) from the pair count.

    The three courses need three equal rings, so n_pairs must be divisible by 3.
    The table rule B_r(x) = {p0[x], p1[x+r], p2[2x+r]} needs 2 to be invertible
    mod the ring size, i.e. the ring size N_RING = n_pairs/3 must be odd. Together
    that means n_pairs is an odd multiple of 3: 3, 9, 15, 21, ..., 63, 69, ...
    (n_pairs % 6 == 3). main() rejects anything else before calling this.
    """
    global N_RING, INV2
    N_RING = n_pairs // 3
    INV2 = pow(2, -1, N_RING)


def build_index_maps():
    x = np.arange(N_RING)
    return {
        0: (x, (x + 1) % N_RING, (2 * x + 2) % N_RING),
        1: (x, x, (2 * x - 2) % N_RING),
        2: ((INV2 * x) % N_RING, (INV2 * (x - 1) + 1) % N_RING, x),
    }


class W:
    """Objective weights."""
    def __init__(self, w_mean, w_tail, w_max, w_leg, alpha, t_target, leg_cap,
                 w_host=0.0, host_cap=math.inf, close=None, w_close=0.0):
        self.w_mean, self.w_tail, self.w_max = w_mean, w_tail, w_max
        self.w_leg, self.alpha = w_leg, alpha
        self.t_target, self.leg_cap = t_target, leg_cap
        self.w_host, self.host_cap = w_host, host_cap
        self.close, self.w_close = close, w_close
        self.seats = None if close is None or not close.any() else meeting_seats(build_index_maps())

    def close_count(self, perms):
        return 0 if self.seats is None else close_meetings(perms, self.seats, self.close)

    @classmethod
    def from_config(cls, t_target, close):
        return cls(config.W_MEAN, config.W_TAIL, config.W_MAX, config.W_LEG,
                   config.ALPHA, t_target, config.LEG_CAP,
                   config.W_HOST, config.HOST_ARRIVE_CAP, close, config.W_MIN_TRAVEL)

    @classmethod
    def mean_only(cls, close):
        return cls(1.0, 0.0, 0.0, 0.0, 0.0, math.inf, math.inf,
                   close=close, w_close=config.W_MIN_TRAVEL)


def per_pair(p0, p1, p2, T1, T2, I, maps):
    """Per-pair (total, [leg1, leg2, leg3]); rows ordered ring0, ring1, ring2."""
    P = (p0, p1, p2)
    ts, lgs = [], []
    for k in range(3):
        a, b, c = maps[k]
        sh, mh, dh = P[0][a], P[1][b], P[2][c]
        l1, l2, l3 = T1[sh, mh], T2[mh, dh], I[dh]
        lgs.append(np.stack([l1, l2, l3], axis=1))
        ts.append(l1 + l2 + l3)
    return np.concatenate(ts), np.concatenate(lgs, axis=0)


def host_arrive_legs(perms, T1, T2, maps):
    """The single leg each main/dessert host travels to reach their own course.

    Ring 1 hosts the main: they arrive from the starter table, leg = T1[sh, mh].
    Ring 2 hosts the dessert: they arrive from the main table, leg = T2[mh, dh].
    The starter host (ring 0) is already home, so it is not included.
    Returns 2*N_RING values, ring1 then ring2.
    """
    p0, p1, p2 = perms
    a1, b1, _ = maps[1]
    main_leg = T1[p0[a1], p1[b1]]
    _, b2, c2 = maps[2]
    dess_leg = T2[p1[b2], p2[c2]]
    return np.concatenate([main_leg, dess_leg])


def close_homes(T1, T2):
    """Symmetric bool matrix: homes less than MIN_TRAVEL_MIN apart in any direction."""
    m = config.MIN_TRAVEL_MIN
    close = (T1 < m) | (T2 < m)
    close = close | close.T
    np.fill_diagonal(close, False)
    return close


def meeting_seats(maps):
    """Seats that must not be close homes, as (ring a, idx a, ring b, idx b) arrays.

    Covers everyone at one table in any round, and both ends of every leg.
    """
    x = np.arange(N_RING)
    seats = {(0, 1): [], (0, 2): [], (1, 2): []}
    for r in range(3):
        s, m, d = x, (x + r) % N_RING, (2 * x + r) % N_RING
        seats[(0, 1)].append((s, m))
        seats[(0, 2)].append((s, d))
        seats[(1, 2)].append((m, d))
    for k in range(3):
        s, m, d = maps[k]
        seats[(0, 1)].append((s, m))
        seats[(1, 2)].append((m, d))
    out = []
    for (ka, kb), pairs in seats.items():
        u = np.unique(np.concatenate([np.stack(p, axis=1) for p in pairs]), axis=0)
        out.append((ka, u[:, 0], kb, u[:, 1]))
    return out


def close_meetings(perms, seats, close):
    """Number of seat pairs that put two close homes together."""
    return sum(int(close[perms[ka][ia], perms[kb][ib]].sum()) for ka, ia, kb, ib in seats)


def host_penalty(perms, T1, T2, maps, w):
    """W_HOST * sum max(0, host_arrival_leg - HOST_ARRIVE_CAP)^2."""
    if w.w_host == 0.0 or not math.isfinite(w.host_cap):
        return 0.0
    e = host_arrive_legs(perms, T1, T2, maps) - w.host_cap
    np.clip(e, 0.0, None, out=e)
    return w.w_host * float(e @ e)


def host_over_cap(perms, T1, T2, maps, w):
    """Number of main/dessert hosts whose arrival leg exceeds HOST_ARRIVE_CAP."""
    if not math.isfinite(w.host_cap):
        return 0
    return int(np.sum(host_arrive_legs(perms, T1, T2, maps) > w.host_cap))


def ring_cost(perms, I, alpha):
    if alpha == 0.0:
        return 0.0
    return alpha * sum(RING_C[k] * float(I[perms[k]].sum()) for k in range(3))


def travel_sum(p0, p1, p2, T1, T2, I, maps):
    """Total per-pair travel, scalar. Hot path for the exact linear layer."""
    s = 0.0
    P = (p0, p1, p2)
    for k in range(3):
        a, b, c = maps[k]
        s += float((T1[P[0][a], P[1][b]] + T2[P[1][b], P[2][c]] + I[P[2][c]]).sum())
    return s


def cost_value(perms, T1, T2, I, maps, w):
    """Full objective. Returns (value, totals-array). No per-leg array built."""
    p0, p1, p2 = perms
    P = (p0, p1, p2)
    parts = []
    legsq = 0.0
    for k in range(3):
        a, b, c = maps[k]
        sh, mh, dh = P[0][a], P[1][b], P[2][c]
        l1, l2, l3 = T1[sh, mh], T2[mh, dh], I[dh]
        parts.append(l1 + l2 + l3)
        if w.w_leg:
            for lg in (l1, l2, l3):
                e = lg - w.leg_cap
                np.clip(e, 0.0, None, out=e)
                legsq += float(e @ e)
    t = np.concatenate(parts)
    tail = t - w.t_target
    np.clip(tail, 0.0, None, out=tail)
    val = (w.w_mean * float(t.mean())
           + w.w_tail * float(tail @ tail)
           + w.w_max * float(t.max())
           + w.w_leg * legsq
           + host_penalty(perms, T1, T2, maps, w)
           + w.w_close * w.close_count(perms)
           + ring_cost(perms, I, w.alpha))
    return val, t


def objective(perms, T1, T2, I, maps, w):
    """Same value as cost_value, but also the (N,3) per-leg array for reports."""
    val, t = cost_value(perms, T1, T2, I, maps, w)
    _, legs = per_pair(*perms, T1, T2, I, maps)
    return val, t, legs


# ---------------------------------------------------------------- exact linear layer
def lsap_ring(perms, k, T1, T2, I, maps, w):
    """Optimal relabelling WITHIN ring k for the sum-of-travel objective.

    With the other two rings fixed no travel term couples two members of ring k,
    so total travel = sum_l g(l, pair_at_l) + const. C[a, l] is that total
    evaluated with pair `a` at label l; the const offset is identical for every
    assignment, so linear_sum_assignment on C minimises the real thing.

    The host-arrival penalty is separable the same way (each label's host leg
    depends only on the pair at that label, once the other rings are fixed), so
    it is added into C and the assignment stays exact for travel + host cost.
    """
    ring_pairs = [int(v) for v in perms[k]]
    base = [p.copy() for p in perms]
    C = np.full((N_RING, N_RING), np.nan)
    pp = [base[0].copy(), base[1].copy(), base[2].copy()]
    col = base[k].copy()
    pp[k] = col
    for li in range(N_RING):
        orig = col[li]
        for ai, a in enumerate(ring_pairs):
            col[li] = a
            C[ai, li] = (travel_sum(*pp, T1, T2, I, maps) + host_penalty(pp, T1, T2, maps, w)
                         + w.w_close * w.close_count(pp))
        col[li] = orig
    assert not np.isnan(C).any(), "cost matrix not fully populated"
    rows, cols = linear_sum_assignment(C)
    new = perms[k].copy()
    for ai, li in zip(rows, cols):
        new[li] = ring_pairs[ai]
    perms[k] = new


def lsap_alternate(perms, T1, T2, I, maps, w, rounds=8):
    prev = None
    for _ in range(rounds):
        for k in (0, 1, 2):
            lsap_ring(perms, k, T1, T2, I, maps, w)
        cur, _ = cost_value(perms, T1, T2, I, maps, w)
        if prev is not None and prev - cur < 1e-6:
            break
        prev = cur


# ---------------------------------------------------------------- annealing layer
# Delta evaluation (recompute only the ~18 pairs at the two touched tables) was
# considered per the brief. It is not a clear win here: the exact linear layer
# already collapses the separable part, the anneal is only polishing the
# non-linear terms over 1.0M iters (~2 min), and the max(T) term needs the global
# maximum re-derived after every accepted move anyway. Full re-evaluation with
# cost_value (no per-leg array built) keeps it simple and correct.
def anneal(perms, T1, T2, I, maps, w, rng, iters):
    cur, _ = cost_value(perms, T1, T2, I, maps, w)
    cur_hv = (w.close_count(perms), host_over_cap(perms, T1, T2, maps, w))
    best, best_hv, best_perms = cur, cur_hv, [p.copy() for p in perms]
    t0, t1 = 6.0, 0.02
    for it in range(iters):
        temp = t0 * (t1 / t0) ** (it / max(iters, 1))
        if rng.random() < 0.35:
            # cross-ring: swap a pair in ring k1 with a pair in ring k2.
            # Ring 2 (dessert) is excluded from cross-ring moves when
            # LOCK_DESSERT_RING is set, so its membership never changes
            # after initial() pins it - only its internal order does, via
            # the within-ring swap branch below and lsap_alternate.
            k1, k2 = (0, 1) if config.LOCK_DESSERT_RING else rng.sample((0, 1, 2), 2)
            i, j = rng.randrange(N_RING), rng.randrange(N_RING)
            perms[k1][i], perms[k2][j] = perms[k2][j], perms[k1][i]
            undo = ("x", k1, i, k2, j)
        else:
            k = rng.randrange(3)
            i, j = rng.randrange(N_RING), rng.randrange(N_RING)
            if i == j:
                continue
            perms[k][i], perms[k][j] = perms[k][j], perms[k][i]
            undo = ("s", k, i, k, j)
        new, _ = cost_value(perms, T1, T2, I, maps, w)
        new_hv = (w.close_count(perms), host_over_cap(perms, T1, T2, maps, w))
        # draw unconditionally so rng consumption per iteration is fixed - a
        # floating-point tie on `new <= cur` must not shift the whole stream
        roll = rng.random()
        # lexicographic on (close homes together, hosts over the cap): refuse any
        # move that makes that worse, always take one that improves it, otherwise
        # ordinary SA on the cost. No close homes and host_cap = inf: a no-op.
        if new_hv < cur_hv or (new_hv == cur_hv
                               and (new <= cur or roll < math.exp((cur - new) / temp))):
            cur, cur_hv = new, new_hv
            if (new_hv, new) < (best_hv, best):
                best, best_hv, best_perms = new, new_hv, [p.copy() for p in perms]
        else:
            _, ka, ia, kb, ib = undo
            perms[ka][ia], perms[kb][ib] = perms[kb][ib], perms[ka][ia]
    return best, best_perms


# ---------------------------------------------------------------- drivers
def initial(rng, I, restart):
    """restart 0 = hard split by distance to Issy; others = random equal thirds.

    With config.LOCK_DESSERT_RING, ring 2 is always the Issy-closest third
    (same set issy_rank_ring would pick) on every restart; only ring 0 vs
    ring 1 varies."""
    ids = list(range(len(I)))
    if config.LOCK_DESSERT_RING:
        pref = issy_rank_ring(I)
        dessert = [i for i in ids if pref[i] == 2]
        rest = [i for i in ids if pref[i] != 2]
        if restart == 0:
            rest = sorted(rest, key=lambda i: -float(I[i]))
        else:
            rng.shuffle(rest)
        rings = [rest[:N_RING], rest[N_RING:], dessert]
    elif restart == 0:
        order = sorted(ids, key=lambda i: -float(I[i]))
        rings = [order[k * N_RING:(k + 1) * N_RING] for k in range(3)]
    else:
        rng.shuffle(ids)
        rings = [ids[k * N_RING:(k + 1) * N_RING] for k in range(3)]
    # shuffle plain lists, not numpy arrays (random.shuffle on an ndarray is a
    # known footgun), then materialise
    for r in rings:
        rng.shuffle(r)
    return [np.array(r, dtype=int) for r in rings]


def search(T1, T2, I, w, rng, iters_total, restarts, anneal_on=True):
    maps = build_index_maps()
    best_obj, best = None, None
    per = max(iters_total // max(restarts, 1), 1)
    for r in range(restarts):
        perms = initial(rng, I, r)
        lsap_alternate(perms, T1, T2, I, maps, w)
        if anneal_on:
            _, perms = anneal(perms, T1, T2, I, maps, w, rng, per)
            lsap_alternate(perms, T1, T2, I, maps, w)
        obj, t, legs = objective(perms, T1, T2, I, maps, w)
        print(f"  restart {r+1}/{restarts}: obj={obj:8.2f}  mean={t.mean():5.1f}  "
              f"sd={t.std():4.1f}  p90={np.percentile(t,90):5.1f}  max={t.max():5.1f}  "
              f"legs>{int(w.leg_cap) if math.isfinite(w.leg_cap) else '-'}"
              f"={int(np.sum(legs > w.leg_cap)) if math.isfinite(w.leg_cap) else 0}")
        if best_obj is None or obj < best_obj:
            best_obj, best = obj, [p.copy() for p in perms]
    return best_obj, best


# ---------------------------------------------------------------- baseline (old algo)
def baseline(T1, T2, I, rng, iters_total, restarts):
    """Reproduce the pre-change result: hard split, objective mean+2.5sd+0.6max,
    within-ring swaps only. Used only for the before/after table."""
    maps = build_index_maps()
    order = sorted(range(len(I)), key=lambda i: -I[i])
    rings0 = [order[k * N_RING:(k + 1) * N_RING] for k in range(3)]

    def obj(perms):
        p0, p1, p2 = perms
        parts = []
        for k in range(3):
            a, b, c = maps[k]
            parts.append(T1[p0[a], p1[b]] + T2[p1[b], p2[c]] + I[p2[c]])
        t = np.concatenate(parts)
        return t.mean() + config.W_STD_OLD * t.std() + config.W_MAX_OLD * t.max()

    best_o, best = None, None
    per = max(iters_total // max(restarts, 1), 1)
    for _ in range(restarts):
        perms = [np.array(r, dtype=int) for r in rings0]
        for p in perms:
            rng.shuffle(p)
        cur = obj(perms)
        b, bp = cur, [p.copy() for p in perms]
        t0, t1 = 6.0, 0.02
        for it in range(per):
            temp = t0 * (t1 / t0) ** (it / per)
            k = rng.randrange(3)
            i, j = rng.randrange(N_RING), rng.randrange(N_RING)
            if i == j:
                continue
            perms[k][i], perms[k][j] = perms[k][j], perms[k][i]
            new = obj(perms)
            if new <= cur or rng.random() < math.exp((cur - new) / temp):
                cur = new
                if new < b:
                    b, bp = new, [q.copy() for q in perms]
            else:
                perms[k][i], perms[k][j] = perms[k][j], perms[k][i]
        if best_o is None or b < best_o:
            best_o, best = b, bp
    return best


# ---------------------------------------------------------------- reporting
def issy_rank_ring(I):
    order = sorted(range(len(I)), key=lambda i: -I[i])
    pref = [0] * len(I)
    for rank, i in enumerate(order):
        pref[i] = min(rank // N_RING, 2)
    return pref


def metrics(perms, T1, T2, I, maps, close):
    t, legs = per_pair(*perms, T1, T2, I, maps)
    ring_of = {}
    for k in range(3):
        for v in perms[k]:
            ring_of[int(v)] = k
    pref = issy_rank_ring(I)
    viol = sum(1 for i in range(len(I)) if ring_of[i] != pref[i])
    hal = host_arrive_legs(perms, T1, T2, maps)
    return {
        "mean": float(t.mean()), "std": float(t.std()),
        "p50": float(np.percentile(t, 50)), "p90": float(np.percentile(t, 90)),
        "max": float(t.max()), "min": float(t.min()),
        "longest_leg": float(legs.max()),
        "legs_over_cap": int(np.sum(legs > config.LEG_CAP)),
        "ring_violations": int(viol),
        "host_arrive_max": float(hal.max()),
        "host_over_cap": int(np.sum(hal > config.HOST_ARRIVE_CAP)),
        "close_meetings": close_meetings(perms, meeting_seats(maps), close),
    }


def print_table(before, after):
    rows = [
        ("mean T (min)", "mean"), ("std T (min)", "std"),
        ("p50 T (min)", "p50"), ("p90 T (min)", "p90"), ("max T (min)", "max"),
        ("longest single leg (min)", "longest_leg"),
        (f"legs over LEG_CAP ({config.LEG_CAP:.0f})", "legs_over_cap"),
        ("longest host-arrival leg (min)", "host_arrive_max"),
        (f"hosts over HOST_ARRIVE_CAP ({config.HOST_ARRIVE_CAP:.0f})", "host_over_cap"),
        (f"homes < {config.MIN_TRAVEL_MIN:.0f} min apart together", "close_meetings"),
        ("ring-order violations", "ring_violations"),
    ]
    print("\n  ================ before / after ================")
    print(f"  {'metric':<28} {'before':>10} {'after':>10}   {'delta':>9}")
    for label, key in rows:
        b, a = before[key], after[key]
        d = a - b
        fb = f"{b:10.1f}" if isinstance(b, float) else f"{b:10d}"
        fa = f"{a:10.1f}" if isinstance(a, float) else f"{a:10d}"
        fd = f"{d:+9.1f}" if isinstance(d, float) else f"{d:+9d}"
        print(f"  {label:<28} {fb} {fa}   {fd}")
    print("  baseline to beat: mean 64.0, std 3.4")
    print("  ===============================================")


def hhmm(minutes_from_midnight):
    m = int(round(minutes_from_midnight))
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def parse_hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


# ---------------------------------------------------------------- travel loader
def load_travel(N):
    trv = json.load(open(TRV, encoding="utf-8"))

    def mat(*keys):
        for k in keys:
            raw = trv.get(k)
            if raw is not None:
                return np.array([[np.nan if v is None else v for v in row] for row in raw],
                                dtype=float)
        raise KeyError(f"data/travel.json has none of {keys}")

    T1 = mat("t1", "full")
    T2 = mat("t2", "full")
    walk = mat("walk", "t1", "full")
    I = np.array(trv["to_issy"], dtype=float)
    mode1 = trv.get("mode1", trv.get("modes"))
    mode2 = trv.get("mode2", trv.get("modes"))
    issy_modes = trv.get("to_issy_mode", [""] * N)

    holes = int(np.isnan(T1).sum() + np.isnan(T2).sum())
    if holes:
        print(f"  WARNING: {holes} empty cells in the travel matrix. With free ring "
              f"membership the solver needs the full {N}x{N} - run  python3 travel.py --yes\n"
              f"           empty cells are treated as a 999-min penalty for now.")
        T1 = np.nan_to_num(T1, nan=999.0)
        T2 = np.nan_to_num(T2, nan=999.0)
        walk = np.nan_to_num(walk, nan=999.0)
    return trv, T1, T2, walk, I, mode1, mode2, issy_modes


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true",
                    help="minimise mean(T) alone, write T_TARGET to data/calibration.json")
    args = ap.parse_args()

    geo = json.load(open(GEO, encoding="utf-8"))
    groups = geo["groups"]
    issy = geo["issy"]
    N = len(groups)
    if N % 3 != 0:
        sys.exit(f"Got {N} pairs. The three courses need three equal rings, so the "
                 f"pair count must be divisible by 3. Fix data/geocoded.json first.")
    if (N // 3) % 2 == 0:
        sys.exit(f"Got {N} pairs -> rings of {N // 3}. The ring size must be ODD so "
                 f"that 2 is invertible mod {N // 3} and 'no pair meets twice' holds "
                 f"(see the module docstring). Use an odd multiple of 3 - e.g. "
                 f"{N - 3} or {N + 3} pairs. Fix data/geocoded.json first.")
    set_ring_size(N)

    trv, T1, T2, walk, I, mode1, mode2, issy_modes = load_travel(N)
    maps = build_index_maps()
    close = close_homes(T1, T2)
    print(f"  homes closer than {config.MIN_TRAVEL_MIN:.0f} min: {int(close.sum()) // 2} combinations kept apart")

    # ---------------------------------------------------------------- calibrate
    if args.calibrate:
        import random
        rng = random.Random(config.SEED)
        w = W.mean_only(close)
        # Minimise mean(T) over the SAME feasible space the real solver uses
        # (free rings, cross-ring moves), so T_TARGET is anchored to a mean that
        # is actually reachable - an LSAP-only pass under-shoots it.
        obj, perms = search(T1, T2, I, w, rng, config.ANNEAL_ITERS // 2,
                            max(config.RESTARTS, 4), anneal_on=True)
        t, _ = per_pair(*perms, T1, T2, I, maps)
        mean_only = float(t.mean())
        t_target = mean_only * (1.0 + config.SLACK)
        json.dump({"mean_only": mean_only, "slack": config.SLACK,
                   "T_TARGET": t_target, "source": trv.get("source", "?")},
                  open(CALIB, "w"), indent=1)
        print(f"\n  calibrate: min mean(T) = {mean_only:.2f} min")
        print(f"  T_TARGET = {mean_only:.2f} * (1 + {config.SLACK}) = {t_target:.2f} min")
        print(f"  -> data/calibration.json")
        return

    # ---------------------------------------------------------------- T_TARGET
    if os.path.exists(CALIB):
        cal = json.load(open(CALIB, encoding="utf-8"))
        t_target = float(cal["T_TARGET"])
        print(f"  T_TARGET = {t_target:.1f} min  (calibrated, data/calibration.json)")
    else:
        t_target = float(config.T_TARGET)
        print(f"  T_TARGET = {t_target:.1f} min  (config.py fallback - run --calibrate)")

    w = W.from_config(t_target, close)

    import random
    rng = random.Random(config.SEED)

    # ---------------------------------------------------------------- baseline
    # The old algorithm is deterministic for a given travel matrix, so cache it.
    src = trv.get("source", "?")
    base_perms = None
    if os.path.exists(BASELINE):
        bl = json.load(open(BASELINE, encoding="utf-8"))
        if bl.get("source") == src and bl.get("seed") == config.SEED:
            base_perms = [np.array(p, dtype=int) for p in bl["perms"]]
            print(f"\n  baseline: reused data/baseline.json ({src})")
    if base_perms is None:
        print("\n  baseline (old hard split, mean + 2.5 sd + 0.6 max) ...")
        base_perms = baseline(T1, T2, I, random.Random(config.SEED),
                              config.ANNEAL_ITERS, config.RESTARTS)
        json.dump({"source": src, "seed": config.SEED,
                   "perms": [[int(v) for v in p] for p in base_perms]},
                  open(BASELINE, "w"), indent=1)
    before = metrics(base_perms, T1, T2, I, maps, close)

    # ---------------------------------------------------------------- new search
    print("\n  new search (free rings, one-sided objective) ...")
    best_obj, best = search(T1, T2, I, w, rng, config.ANNEAL_ITERS, config.RESTARTS)
    p0, p1, p2 = best
    after = metrics(best, T1, T2, I, maps, close)
    t_all, _ = per_pair(p0, p1, p2, T1, T2, I, maps)

    pref = issy_rank_ring(I)
    ring_of = {}
    for k in range(3):
        for v in best[k]:
            ring_of[int(v)] = k
    outside = [i for i in range(N) if ring_of[i] != pref[i]]

    print_table(before, after)
    print(f"\n  pairs outside their Issy-rank ring: {len(outside)}/{N}")

    if after["host_over_cap"] > 0:
        print(f"\n  !!! WARNING: {after['host_over_cap']} host(s) travel more than "
              f"{config.HOST_ARRIVE_CAP:.0f} min to the course they host - they will be "
              f"short on cooking time.\n"
              f"      Longest host-arrival leg: {after['host_arrive_max']:.1f} min. "
              f"Raise W_HOST in config.py or re-run with a new SEED before sending anything out.")
    else:
        print(f"  every host reaches their own course in <= {config.HOST_ARRIVE_CAP:.0f} min "
              f"(longest {after['host_arrive_max']:.1f})")

    if after["close_meetings"] > 0:
        print(f"\n  !!! WARNING: {after['close_meetings']} meeting(s) or leg(s) between homes less "
              f"than {config.MIN_TRAVEL_MIN:.0f} min apart.\n"
              f"      Re-run with a new SEED or lower MIN_TRAVEL_MIN before sending anything out.")
    else:
        print(f"  no homes closer than {config.MIN_TRAVEL_MIN:.0f} min share a table or a leg")

    pos = [{int(v): x for x, v in enumerate(p)} for p in (p0, p1, p2)]

    # ---------------------------------------------------------------- tables
    tables = {c: [] for c in COURSES}
    for r, course in enumerate(COURSES):
        for x in range(N_RING):
            members = [int(p0[x]), int(p1[(x + r) % N_RING]), int(p2[(2 * x + r) % N_RING])]
            host = members[r]
            tables[course].append({"table": x, "host": host, "members": members})

    # ---------------------------------------------------------------- verify
    seen = {}
    for course in COURSES:
        for tb in tables[course]:
            ms = tb["members"]
            assert len(set(ms)) == 3, "duplicate pair at a table"
            for a in range(3):
                for b in range(a + 1, 3):
                    k = tuple(sorted((ms[a], ms[b])))
                    if k in seen:
                        sys.exit(f"REPEAT MEETING {k} in {seen[k]} and {course}")
                    seen[k] = course
    hosts = [0] * N
    for course in COURSES:
        for tb in tables[course]:
            hosts[tb["host"]] += 1
    assert all(h == 1 for h in hosts), "some pair hosts more or less than once"
    for course in COURSES:
        assert sorted(m for tb in tables[course] for m in tb["members"]) == list(range(N))
    print(f"\n  verified: {N} pairs x 3 courses, {N_RING} tables each, every pair hosts "
          f"once, {len(seen)} distinct encounters, 0 repeats")

    # ---------------------------------------------------------------- routes
    where = {c: {} for c in COURSES}
    for course in COURSES:
        for tb in tables[course]:
            for m in tb["members"]:
                where[course][m] = tb

    arr = {c: parse_hhmm(a) for c, a in
           zip(COURSES, [config.ARRIVE_STARTER, config.ARRIVE_MAIN, config.ARRIVE_DESSERT])}
    arr_issy = parse_hhmm(config.ARRIVE_AFTERPARTY)

    idx2gid = [g["group_id"] for g in groups]
    gmeta = {g["group_id"]: g for g in groups}

    def leg(mat, modes, a, b):
        v = mat[a, b]
        mo = modes[a][b] if modes else ""
        return (None if np.isnan(v) else float(v)), mo

    routes = []
    for i in range(N):
        sh = where["starter"][i]["host"]
        mh = where["main"][i]["host"]
        dh = where["dessert"][i]["host"]
        l1, m1 = leg(T1, mode1, sh, mh)
        l2, m2 = leg(T2, mode2, mh, dh)
        l3, m3 = float(I[dh]), issy_modes[dh]
        h2s = 0.0 if sh == i else float(min(walk[i, sh], T1[i, sh]))
        host_course = ("starter" if sh == i else "main" if mh == i else "dessert")
        # the single leg this pair travels to reach the course they host
        host_arrive_min = (h2s if host_course == "starter"
                           else (l1 or 0.0) if host_course == "main"
                           else (l2 or 0.0))
        pi = (0 if i in pos[0] else N_RING if i in pos[1] else 2 * N_RING)
        pi += pos[0].get(i, pos[1].get(i, pos[2].get(i, 0)))
        routes.append({
            "group": idx2gid[i],
            "hosts": host_course,
            "ring": ring_of[i],
            "ring_pref": pref[i],
            "ring_violation": ring_of[i] != pref[i],
            "home_to_starter_min": h2s,
            "host_arrive_min": float(host_arrive_min),
            "host_arrive_over_cap": bool(host_arrive_min > config.HOST_ARRIVE_CAP),
            "stops": [
                {"course": "starter", "host": idx2gid[sh], "table": where["starter"][i]["table"],
                 "arrive": hhmm(arr["starter"]),
                 "co": [idx2gid[m] for m in where["starter"][i]["members"] if m != i]},
                {"course": "main", "host": idx2gid[mh], "table": where["main"][i]["table"],
                 "arrive": hhmm(arr["main"]),
                 "co": [idx2gid[m] for m in where["main"][i]["members"] if m != i]},
                {"course": "dessert", "host": idx2gid[dh], "table": where["dessert"][i]["table"],
                 "arrive": hhmm(arr["dessert"]),
                 "co": [idx2gid[m] for m in where["dessert"][i]["members"] if m != i]},
            ],
            "legs": [
                {"from": idx2gid[sh], "to": idx2gid[mh], "min": l1, "mode": m1,
                 "depart": hhmm(arr["main"] - (l1 or 0)), "arrive": hhmm(arr["main"])},
                {"from": idx2gid[mh], "to": idx2gid[dh], "min": l2, "mode": m2,
                 "depart": hhmm(arr["dessert"] - (l2 or 0)), "arrive": hhmm(arr["dessert"])},
                {"from": idx2gid[dh], "to": "ISSY", "min": l3, "mode": m3,
                 "depart": hhmm(arr_issy - l3), "arrive": hhmm(arr_issy)},
            ],
            "total_min": float(t_all[pi]),
        })

    # host-side info
    host_info = {}
    for course in COURSES:
        for tb in tables[course]:
            h = idx2gid[tb["host"]]
            allerg, alco = [], []
            for m in tb["members"]:
                who = f"{gmeta[idx2gid[m]]['name1']}/{gmeta[idx2gid[m]]['name2']}"
                a = gmeta[idx2gid[m]].get("allergies", "").strip()
                if a and a not in (".", "-"):
                    allerg.append(f"{who}: {a}")
                d = gmeta[idx2gid[m]].get("alkoholpreferenser", "").strip()
                if d and d not in (".", "-"):
                    alco.append(f"{who}: {d}")
            host_info[h] = {
                "course": course, "table": tb["table"],
                "guests": [idx2gid[m] for m in tb["members"] if m != tb["host"]],
                "allergies": allerg,
                "alkoholpreferenser": alco,
                "arrive": hhmm(arr[course]),
            }

    payload = {
        "meta": {
            "date": config.EVENT_DATE, "issy": issy,
            "afterparty": {"name": config.AFTERPARTY_NAME,
                           "address": config.AFTERPARTY_ADDRESS.replace(", Sweden", "")},
            "arrive": {"starter": config.ARRIVE_STARTER, "main": config.ARRIVE_MAIN,
                       "dessert": config.ARRIVE_DESSERT, "afterparty": config.ARRIVE_AFTERPARTY},
            "travel_source": trv.get("source", "?"),
            "t_target": t_target, "leg_cap": config.LEG_CAP,
            "host_arrive_cap": config.HOST_ARRIVE_CAP,
            "stats": {"mean": after["mean"], "sd": after["std"],
                      "min": after["min"], "max": after["max"],
                      "p50": after["p50"], "p90": after["p90"],
                      "longest_leg": after["longest_leg"],
                      "legs_over_cap": after["legs_over_cap"],
                      "host_arrive_max": after["host_arrive_max"],
                      "host_over_cap": after["host_over_cap"],
                      "close_meetings": after["close_meetings"],
                      "ring_violations": after["ring_violations"],
                      "objective": float(best_obj)},
            "baseline": before,
        },
        "groups": [{k: g.get(k, "") for k in ("group_id", "name1", "name2", "address", "formatted",
                                              "lat", "lng", "phone1", "phone2", "email",
                                              "allergies", "alkoholpreferenser")}
                   for g in groups],
        "tables": {c: [{"table": tb["table"], "host": idx2gid[tb["host"]],
                        "members": [idx2gid[m] for m in tb["members"]]} for tb in tables[c]]
                   for c in COURSES},
        "routes": routes,
        "host_info": host_info,
    }
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n  travel per pair (min):  mean {after['mean']:.1f}   sd {after['std']:.1f}   "
          f"p90 {after['p90']:.1f}   max {after['max']:.1f}")
    print(f"  -> data/schedule.json")


if __name__ == "__main__":
    main()
