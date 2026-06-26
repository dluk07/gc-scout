# gc-scout — GameChanger Strength-of-Schedule & Matchup Scout

Pulls your team's and your opponents' public GameChanger results, builds a results
graph, and computes **strength of schedule** + a **projected matchup** for one or more
candidate opponents (e.g. "Saturday we play the winner of A vs B — how do we match up
against each?").

**📊 Live report:** https://dluk07.github.io/gc-scout/

## How it works

GameChanger has no public API, but the **public team-profile** endpoints behind
`web.gc.com/teams/<id>` are reachable and need **no login/token**:

- `GET /public/teams/{shortId}` → name, location, season `record {win,loss,tie}`
- `GET /public/teams/{shortId}/games` → every game with `score {team, opponent_team}`,
  opponent name, date, home/away, status

`shortId` is the 12-char id in a team's URL, e.g.
`web.gc.com/teams/`**`9rpA1Riw3pSY`**`/2026-summer-8u-mischiefs-c-8u/schedule`.

Opponents in the feed are identified by **name only**, so the tool uses normalized team
names as graph nodes — which naturally captures **common opponents** between teams. The
analysis:

1. **Collect** (`crawl.py`) — fetch each seed team's profile + games, dedup, normalize.
2. **Rate** (`analyze.py`) — Massey least-squares on game margins (home-field + ridge), a
   chronological Elo cross-check, and an **opponent-adjusted offense/defense split** (a
   two-way least-squares model: `runs = mean + OFF[scorer] − DEF[defender] + home`, so
   beating weak teams inflates raw runs but not the adjusted ratings).
3. **Project** — blend the rating gap with **common-opponent** and **head-to-head**
   margins (the common-opponent signal controls for schedule strength), → expected run
   margin + win probability + a confidence flag, plus a per-opponent "prepare for a
   strong/weak offense & defense" readout with expected runs scored/allowed.
4. **Report** (`report.py`) — scouting cards, common-opponent tables, an SoS leaderboard
   (your team + next opponents highlighted), and a **glossary**, rendered as Markdown +
   CSV + a styled **HTML report with charts** (a power-rankings bar and an
   offense-vs-defense quadrant scatter, via Chart.js) in `reports/`.

> Note: only **seed** teams (ids you pass) have full schedules; other teams appear only
> via games against the seeds, so their ratings use partial data. Youth results are noisy
> and name-matching is fuzzy — projections are directional. Using these endpoints is
> against GameChanger's [Terms of Use](https://gc.com/terms); this is personal,
> low-volume, cached use.

## Setup

```bash
pip install -r requirements.txt
```

No `.env`/token is required for the public endpoints. (A `GC_TOKEN` is only needed for the
coach-API probe scripts; see below.)

## Run

Grab the short ids from each team's `web.gc.com/teams/<id>/...` URL, then:

```bash
python main.py --me 9rpA1Riw3pSY --opponents U3SbqWb4YPke,BUZ2EzE23lWB
python main.py --me <id> --opponents <id1>,<id2> --refresh        # bust the cache
python main.py --me <id> --opponents <id1>,<id2> --extra <id3>,<id4>   # deepen SoS
python main.py --me <id> --opponents <id1>,<id2> --publish        # also write docs/index.html
```

It prints a quick projection and writes `reports/scouting_<date>.{html,md,csv}` (the HTML
opens automatically). `--publish` also copies the HTML to `docs/index.html`, which is what
GitHub Pages serves at the live link above. To deepen strength-of-schedule, look up the
opponents it lists as "non-seed" on web.gc.com and pass their ids via `--opponents`/`--extra`.

## Files

- `main.py` — CLI
- `gc_api.py` — public API client + on-disk cache (`cache/`, 6h TTL)
- `crawl.py` — collection + name normalization + dedup
- `analyze.py` — Massey/Elo ratings, opponent-adjusted offense/defense, SoS, projection
- `report.py` — Markdown + CSV + charted HTML output
- `docs/index.html` — the published report (GitHub Pages source)

## Notes

- `.env`, `cache/`, `reports/`, `games.json`, and the `probe*.py` discovery scripts are
  gitignored (the probes need a `GC_TOKEN` and held captured tokens, so they stay local).
- Caching: per-team JSON under `cache/`; `--refresh` to refetch.
- `TBD …` placeholder opponents are ignored automatically.
