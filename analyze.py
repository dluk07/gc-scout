"""
analyze.py — turn the collected results graph into records, ratings, strength of
schedule, and head-to-head projections.

Models:
  * Massey ratings: least-squares on game margins with a home-field term and ridge
    regularization (stabilizes thinly-connected teams). Ratings are on a runs scale,
    centered at 0 — a rating of +3 means "~3 runs better than an average team here".
  * Elo: chronological, margin-aware, as an independent cross-check + win prob.

Projection for ME vs each candidate uses the Massey rating gap (neutral field by
default) -> expected run margin -> win probability, plus direct head-to-head and
common-opponent evidence, with a confidence flag driven by how connected the data is.
"""
import math
from collections import defaultdict

import numpy as np

SIGMA = 3.6          # runs scale: ~5-run edge -> ~80% win prob
RIDGE = 0.30         # pulls sparse teams toward average
RIDGE_OD = 0.40      # off/def model: a touch more shrinkage (twice the unknowns)
ELO_K = 24.0
TBD_PREFIX = "tbd"


def _real_games(data):
    out = []
    for g in data["games"]:
        if g["a"].startswith(TBD_PREFIX) or g["b"].startswith(TBD_PREFIX):
            continue
        if not g["a"] or not g["b"]:
            continue
        out.append(g)
    return out


# ---------------------------------------------------------------- Massey ratings
def massey(data):
    games = _real_games(data)
    teams = sorted({g["a"] for g in games} | {g["b"] for g in games})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    rows, rhs = [], []
    for g in games:
        row = [0.0] * (n + 1)          # last col = home-field advantage
        row[idx[g["a"]]] += 1.0
        row[idx[g["b"]]] -= 1.0
        row[n] += 1.0 if g["home"] else -1.0
        rows.append(row)
        rhs.append(g["a_score"] - g["b_score"])
    # constraint: sum of team ratings = 0
    c = [1.0] * n + [0.0]
    rows.append(c); rhs.append(0.0)
    # ridge: each team rating pulled toward 0
    for i in range(n):
        r = [0.0] * (n + 1); r[i] = RIDGE
        rows.append(r); rhs.append(0.0)
    A = np.array(rows); b = np.array(rhs)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    ratings = {t: float(sol[idx[t]]) for t in teams}
    home_adv = float(sol[n])
    return ratings, home_adv


# ---------------------------------------------------------------- offense / defense
def off_def(data):
    """Opponent-adjusted offensive and defensive ratings on a runs scale.

    Two observations per game (each team's runs scored):
        runs = mu + OFF[scorer] - DEF[defender] + h*(scorer is home)
    Least-squares for OFF/DEF per team, a league mean `mu`, and a home boost `h`,
    with each OFF/DEF centered at 0 (sum=0) and ridge-shrunk toward average.

    Interpretation (both in runs, vs an average team here):
        OFF > 0  -> scores more than average even against equal defenses
        DEF > 0  -> *allows fewer* than average even against equal offenses (good D)
    So expected runs for me vs opp = mu + OFF[me] - DEF[opp].
    """
    games = _real_games(data)
    teams = sorted({g["a"] for g in games} | {g["b"] for g in games})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    O = lambda t: idx[t]            # OFF block:  [0 .. n-1]
    D = lambda t: n + idx[t]        # DEF block:  [n .. 2n-1]
    MU, H = 2 * n, 2 * n + 1        # mean, home boost
    width = 2 * n + 2

    rows, rhs = [], []

    def obs(scorer, defender, runs, scorer_home):
        row = [0.0] * width
        row[O(scorer)] += 1.0
        row[D(defender)] -= 1.0
        row[MU] += 1.0
        if scorer_home:
            row[H] += 1.0
        rows.append(row); rhs.append(float(runs))

    for g in games:
        a_home = bool(g["home"])
        obs(g["a"], g["b"], g["a_score"], a_home)        # team a's runs
        obs(g["b"], g["a"], g["b_score"], not a_home)    # team b's runs

    # center each block so OFF and DEF are read against the league average
    for block in (range(0, n), range(n, 2 * n)):
        c = [0.0] * width
        for j in block:
            c[j] = 1.0
        rows.append(c); rhs.append(0.0)
    # ridge: shrink each OFF/DEF toward 0 (mu and h left free)
    for j in range(2 * n):
        r = [0.0] * width; r[j] = RIDGE_OD
        rows.append(r); rhs.append(0.0)

    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    off = {t: float(sol[O(t)]) for t in teams}
    deff = {t: float(sol[D(t)]) for t in teams}
    return {"off": off, "def": deff, "mu": float(sol[MU]), "home": float(sol[H])}


# ---------------------------------------------------------------- Elo ratings
def elo(data):
    games = sorted(_real_games(data), key=lambda g: g["date"])
    R = defaultdict(lambda: 1500.0)
    for g in games:
        ra, rb = R[g["a"]], R[g["b"]]
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        margin = g["a_score"] - g["b_score"]
        sa = 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
        mov = math.log(abs(margin) + 1.0)
        R[g["a"]] = ra + ELO_K * mov * (sa - ea)
        R[g["b"]] = rb + ELO_K * mov * ((1.0 - sa) - (1.0 - ea))
    return dict(R)


# ---------------------------------------------------------------- per-team summary
def team_summary(data, ratings, elo_r, od):
    games = _real_games(data)
    by_team = defaultdict(list)
    for g in games:
        by_team[g["a"]].append((g["date"], g["a_score"], g["b_score"], g["b"]))
        by_team[g["b"]].append((g["date"], g["b_score"], g["a_score"], g["a"]))

    summ = {}
    for t, gl in by_team.items():
        gl.sort()
        w = sum(1 for _, s, o, _ in gl if s > o)
        l = sum(1 for _, s, o, _ in gl if s < o)
        ti = sum(1 for _, s, o, _ in gl if s == o)
        margins = [s - o for _, s, o, _ in gl]
        scored = [s for _, s, o, _ in gl]
        allowed = [o for _, s, o, _ in gl]
        opp_ratings = [ratings.get(opp, 0.0) for _, _, _, opp in gl]
        last5 = gl[-5:]
        l5w = sum(1 for _, s, o, _ in last5 if s > o)
        l5l = sum(1 for _, s, o, _ in last5 if s < o)
        info = data["teams"].get(t, {})
        summ[t] = {
            "display": info.get("display", t),
            "is_seed": info.get("is_seed", False),
            "api_record": info.get("record"),
            "short_id": info.get("short_id"),
            "gp": len(gl), "w": w, "l": l, "t": ti,
            "win_pct": (w + 0.5 * ti) / len(gl) if gl else 0.0,
            "avg_margin": sum(margins) / len(margins) if margins else 0.0,
            "massey": ratings.get(t, 0.0),
            "elo": elo_r.get(t, 1500.0),
            "sos": sum(opp_ratings) / len(opp_ratings) if opp_ratings else 0.0,
            "last5": f"{l5w}-{l5l}",
            # offense / defense (opponent-adjusted, runs vs avg) + raw per-game rates
            "off": od["off"].get(t, 0.0),
            "def": od["def"].get(t, 0.0),
            "rs_pg": sum(scored) / len(scored) if scored else 0.0,
            "ra_pg": sum(allowed) / len(allowed) if allowed else 0.0,
        }
    return summ


# ---------------------------------------------------------------- projection
def common_opponents(data, me, opp):
    games = _real_games(data)
    res = defaultdict(lambda: {"me": [], "opp": []})
    for g in games:
        for who, other in ((g["a"], g["b"]), (g["b"], g["a"])):
            if who == me:
                s, o = (g["a_score"], g["b_score"]) if g["a"] == me else (g["b_score"], g["a_score"])
                res[other]["me"].append(s - o)
            if who == opp:
                s, o = (g["a_score"], g["b_score"]) if g["a"] == opp else (g["b_score"], g["a_score"])
                res[other]["opp"].append(s - o)
    common = {}
    for team, d in res.items():
        if team in (me, opp):
            continue
        if d["me"] and d["opp"]:
            common[team] = d
    return common


def head_to_head(data, me, opp):
    out = []
    for g in _real_games(data):
        pair = {g["a"], g["b"]}
        if pair == {me, opp}:
            if g["a"] == me:
                out.append((g["date"], g["a_score"], g["b_score"]))
            else:
                out.append((g["date"], g["b_score"], g["a_score"]))
    return out


def project(data, me, opp, ratings, summ, od, home=None):
    # --- three independent signals for the expected run margin (me - opp) ---
    massey_margin = ratings.get(me, 0.0) - ratings.get(opp, 0.0)

    common = common_opponents(data, me, opp)
    # common-opponent margin: how much better you did than them vs shared teams.
    # This controls for schedule strength (the thing raw ratings can over/under-credit).
    common_edges = []
    for d in common.values():
        common_edges.append(sum(d["me"]) / len(d["me"]) - sum(d["opp"]) / len(d["opp"]))
    common_margin = sum(common_edges) / len(common_edges) if common_edges else None

    h2h = head_to_head(data, me, opp)
    h2h_margin = sum(a - b for _, a, b in h2h) / len(h2h) if h2h else None

    # --- blend, weighting each signal by how much evidence backs it ---
    w_massey = 1.0
    w_common = min(len(common_edges), 8) / 8.0 * 1.5
    w_h2h = min(len(h2h), 3) * 0.8
    num = massey_margin * w_massey
    den = w_massey
    if common_margin is not None:
        num += common_margin * w_common; den += w_common
    if h2h_margin is not None:
        num += h2h_margin * w_h2h; den += w_h2h
    blended = num / den
    win_p = 1.0 / (1.0 + math.exp(-blended / SIGMA))

    cc = len(common)
    conf_score = cc + (2 if h2h else 0) + min(summ.get(opp, {}).get("gp", 0), 6) / 6.0
    conf = "moderate" if conf_score >= 5 else ("low-moderate" if conf_score >= 3 else "low")

    # --- offense/defense breakdown: what to prepare for ---
    mu = od["mu"]
    exp_rs = mu + od["off"].get(me, 0.0) - od["def"].get(opp, 0.0)   # what you'll score
    exp_ra = mu + od["off"].get(opp, 0.0) - od["def"].get(me, 0.0)   # what they'll score
    matchup = {
        "exp_rs": max(0.0, exp_rs), "exp_ra": max(0.0, exp_ra),
        "opp_off": od["off"].get(opp, 0.0), "opp_def": od["def"].get(opp, 0.0),
        "opp_off_label": strength_label(od["off"].get(opp, 0.0)),
        "opp_def_label": strength_label(od["def"].get(opp, 0.0)),
    }

    return {
        "me": me, "opp": opp,
        "exp_margin": blended, "win_pct": win_p,
        "massey_margin": massey_margin, "common_margin": common_margin,
        "h2h_margin": h2h_margin,
        "h2h": h2h, "common": common,
        "n_common": cc, "confidence": conf,
        "matchup": matchup,
    }


def strength_label(rating):
    """Map an off/def rating (runs vs average) to a prep word."""
    if rating >= 2.0:
        return "very strong"
    if rating >= 0.8:
        return "strong"
    if rating > -0.8:
        return "average"
    if rating > -2.0:
        return "weak"
    return "very weak"


def analyze(data, my_id_name, opponent_names):
    ratings, home_adv = massey(data)
    elo_r = elo(data)
    od = off_def(data)
    summ = team_summary(data, ratings, elo_r, od)
    projections = [project(data, my_id_name, opp, ratings, summ, od) for opp in opponent_names]
    return {"summary": summ, "home_adv": home_adv, "off_def": od,
            "projections": projections, "ratings": ratings}
