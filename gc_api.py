"""
gc_api.py — client for GameChanger's PUBLIC team-profile API.

Confirmed during Phase 0 discovery (see probe*.py):
  GET /public/teams/{shortId}            -> team info + team_season.record {win,loss,tie}
  GET /public/teams/{shortId}/games      -> all games w/ score {team, opponent_team},
                                            opponent_team.name, start_ts, home_away, status

These are PUBLIC (no auth required), but we send the web-app headers (and the token if
present) to look like the real client and avoid the AWS WAF. shortId is the 12-char id
from a web.gc.com/teams/<shortId>/... URL.

Results are cached on disk under cache/ so repeated runs / shared opponents don't re-hit
the API. Use refresh=True (or main.py --refresh) to bust the cache.
"""
import os
import json
import time
import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE = "https://api.team-manager.gc.com"
CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 6 * 3600
_LAST_CALL = [0.0]
_MIN_INTERVAL = 0.4  # polite spacing between live calls

_TOKEN = os.environ.get("GC_TOKEN", "").strip()
_HEADERS = {
    "accept": "application/json",
    "accept-language": "en-US,en;q=0.9",
    "gc-app-name": "web",
    "origin": "https://web.gc.com",
    "referer": "https://web.gc.com/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"),
}
if _TOKEN:
    _HEADERS["gc-token"] = _TOKEN


class GCError(Exception):
    pass


def _log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")


def _cache_path(key):
    safe = key.replace("/", "_").strip("_")
    return CACHE / f"{safe}.json"


def _get(path, key, refresh=False):
    """GET with on-disk caching, rate-limiting, and retry/backoff."""
    cp = _cache_path(key)
    if not refresh and cp.exists():
        age = time.time() - cp.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            try:
                return json.loads(cp.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass  # fall through to live fetch

    # rate limit
    wait = _MIN_INTERVAL - (time.time() - _LAST_CALL[0])
    if wait > 0:
        time.sleep(wait)

    last_err = None
    for attempt in range(4):
        try:
            r = requests.get(BASE + path, headers=_HEADERS, timeout=30)
            _LAST_CALL[0] = time.time()
        except requests.RequestException as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                raise GCError(f"Non-JSON 200 from {path}")
            cp.write_text(json.dumps(data), encoding="utf-8")
            return data
        if r.status_code in (429, 500, 502, 503):
            time.sleep(1.5 * (attempt + 1))
            last_err = GCError(f"{r.status_code} from {path}")
            continue
        if r.status_code in (401, 403):
            raise GCError(f"{r.status_code} from {path} — token may be expired/blocked. "
                          "Public reads usually don't need a token; check headers/WAF.")
        if r.status_code == 404:
            raise GCError(f"404 — team not found or wrong id: {path}")
        raise GCError(f"Unexpected {r.status_code} from {path}")
    raise GCError(f"Failed after retries: {path} ({last_err})")


def get_team(short_id, refresh=False):
    """Team profile: name, location, age_group, team_season.record {win,loss,tie}."""
    return _get(f"/public/teams/{short_id}", f"team_{short_id}", refresh)


def get_games(short_id, refresh=False):
    """All games for a team: list of {id, opponent_team{name}, start_ts, home_away,
    score{team, opponent_team}, game_status, ...}."""
    return _get(f"/public/teams/{short_id}/games", f"games_{short_id}", refresh)


if __name__ == "__main__":  # quick smoke test
    import sys
    tid = sys.argv[1] if len(sys.argv) > 1 else "9rpA1Riw3pSY"
    t = get_team(tid)
    rec = t.get("team_season", {}).get("record", {})
    print(f"{t.get('name')} — {rec.get('win')}-{rec.get('loss')}-{rec.get('tie')}")
    gs = get_games(tid)
    done = [g for g in gs if g.get("game_status") == "completed" and g.get("score")]
    print(f"{len(gs)} games, {len(done)} completed with score")
    for g in done[:3]:
        s = g["score"]
        print(f"  {g['start_ts'][:10]} vs {g['opponent_team']['name']:24s} "
              f"{s['team']}-{s['opponent_team']} ({g['home_away']})")
