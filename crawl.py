"""
crawl.py — collect public games for a set of seed team short-ids and normalize them
into a results graph.

Opponents in the feed are named (no id), so we use normalized team NAMES as graph
nodes. Seed teams (the ids you pass) get authoritative records from the profile API;
non-seed opponents appear only via the seeds' games (partial), which is still enough to
connect the graph for ratings and common-opponent analysis.

Output: a dict with
  teams: {canon_name: {display, short_id|None, is_seed, record{win,loss,tie}|None}}
  games: [{date, a, b, a_score, b_score, home, source_ids}]   (a/b are canon names; an
         edge per game, deduped across the two perspectives)
"""
import re
import datetime

import gc_api

AGE_TOKEN = re.compile(r"\b\d{1,2}u\b")
NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
WS = re.compile(r"\s+")


def canon(name):
    """Normalize a team name for matching: lowercase, drop age tokens (8u/10u),
    strip punctuation, collapse whitespace."""
    if not name:
        return ""
    s = name.lower()
    s = AGE_TOKEN.sub(" ", s)
    s = NON_ALNUM.sub(" ", s)
    s = WS.sub(" ", s).strip()
    return s


def _log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")


def collect(seed_ids, refresh=False):
    teams = {}
    raw_games = []

    for sid in seed_ids:
        try:
            prof = gc_api.get_team(sid, refresh=refresh)
            games = gc_api.get_games(sid, refresh=refresh)
        except gc_api.GCError as e:
            _log(f"  ! {sid}: {e}")
            continue
        name = prof.get("name", sid)
        cn = canon(name)
        rec = prof.get("team_season", {}).get("record")
        teams[cn] = {"display": name, "short_id": sid, "is_seed": True, "record": rec}
        done = [g for g in games if g.get("game_status") == "completed" and g.get("score")]
        _log(f"  + {name}: {len(done)} completed games "
             f"(record {rec.get('win')}-{rec.get('loss')}-{rec.get('tie')})" if rec else name)

        for g in done:
            opp_name = (g.get("opponent_team") or {}).get("name", "")
            ocn = canon(opp_name)
            if not ocn:
                continue
            # register opponent as a (non-seed) node if unseen
            if ocn not in teams:
                teams[ocn] = {"display": opp_name, "short_id": None,
                              "is_seed": False, "record": None}
            sc = g["score"]
            raw_games.append({
                "date": (g.get("start_ts") or "")[:10],
                "a": cn, "b": ocn,
                "a_score": sc.get("team"), "b_score": sc.get("opponent_team"),
                "home": (g.get("home_away") == "home"),
                "gid": g.get("id"),
            })

    games = _dedup(raw_games)
    _log(f"collected {len(games)} unique games across {len(teams)} teams "
         f"({sum(1 for t in teams.values() if t['is_seed'])} seeds)")
    return {"teams": teams, "games": games}


def _dedup(raw):
    """The same physical game shows up from both teams' feeds. Collapse by
    (date, unordered team pair, unordered score)."""
    seen = {}
    for g in raw:
        if g["a_score"] is None or g["b_score"] is None:
            continue
        key = (g["date"], frozenset((g["a"], g["b"])),
               frozenset((g["a_score"], g["b_score"])))
        if key not in seen:
            seen[key] = dict(g, source_ids=[g["gid"]])
        else:
            seen[key]["source_ids"].append(g["gid"])
    return list(seen.values())


if __name__ == "__main__":
    import sys, json
    ids = sys.argv[1:] or ["9rpA1Riw3pSY", "U3SbqWb4YPke", "BUZ2EzE23lWB"]
    data = collect(ids)
    print(json.dumps({"teams": {k: v["display"] for k, v in data["teams"].items()},
                      "n_games": len(data["games"])}, indent=2)[:1500])
