"""
report.py — render the analysis into a printable Markdown scouting report + a CSV of
the ratings table, plus a charted HTML report and a Pages index of all reports.
"""
import html
import datetime


def _rec(r):
    if not r:
        return "n/a"
    return f"{r.get('win')}-{r.get('loss')}-{r.get('tie')}"


def _fmt_margin(m):
    if m >= 0:
        return f"+{m:.1f}"
    return f"{m:.1f}"


# ---- colored stat spans (survive markdown -> HTML as inline HTML) -------------
def _signed(val, unit="", good_high=True, hi=0.8, lo=-0.8):
    """Color a signed runs-scale stat: green=good, red=bad, gray=neutral.
    good_high=True means a higher value is better (power, offense, defense, margin)."""
    if val >= hi:
        cls = "good" if good_high else "bad"
    elif val <= lo:
        cls = "bad" if good_high else "good"
    else:
        cls = "neu"
    return f"<span class='stat {cls}'>{_fmt_margin(val)}{unit}</span>"


def _pct(p):
    """Color a win probability: green > 55%, red < 45%, gray between."""
    cls = "good" if p >= 0.55 else ("bad" if p <= 0.45 else "neu")
    return f"<span class='stat {cls}'>{p*100:.0f}%</span>"


def _sos(val):
    """Color strength-of-schedule: amber = tough slate, blue = soft slate."""
    cls = "tough" if val >= 0.4 else ("soft" if val <= -0.4 else "neu")
    return f"<span class='stat {cls}'>{_fmt_margin(val)}</span>"


def _label_span(word):
    """Color a strong/weak prep label."""
    cls = {"very strong": "good", "strong": "good",
           "weak": "bad", "very weak": "bad"}.get(word, "neu")
    return f"<span class='stat {cls}'>{word}</span>"


def _scouting_card(s):
    rec = _rec(s["api_record"]) if s["api_record"] else f"{s['w']}-{s['l']}-{s['t']}"
    return (
        f"### {s['display']}\n"
        f"- Record: **{rec}**  (win% {s['win_pct']*100:.0f}%, last5 {s['last5']})\n"
        f"- Power rating (Massey): {_signed(s['massey'], ' runs')}  ·  Elo {s['elo']:.0f}\n"
        f"- Offense: {_signed(s['off'], ' runs')} adj  ·  {s['rs_pg']:.1f} runs scored/game\n"
        f"- Defense: {_signed(s['def'], ' runs')} adj  ·  {s['ra_pg']:.1f} runs allowed/game\n"
        f"- Strength of schedule: {_sos(s['sos'])} (avg opponent rating)\n"
        f"- Avg margin: {_signed(s['avg_margin'], ' runs')} over {s['gp']} games\n"
    )


def _common_table(common, summ):
    if not common:
        return "_No common opponents found in the collected data._\n"
    rows = ["| Common opponent | Your result(s) | Their result(s) | Edge |",
            "|---|---|---|---|"]
    # sort by how much it favors "me"
    def avg(xs):
        return sum(xs) / len(xs)
    for team, d in sorted(common.items(), key=lambda kv: avg(kv[1]["me"]) - avg(kv[1]["opp"]), reverse=True):
        me_avg, opp_avg = avg(d["me"]), avg(d["opp"])
        disp = summ.get(team, {}).get("display", team)
        edge = me_avg - opp_avg
        me_s = ", ".join(_fmt_margin(x) for x in d["me"])
        opp_s = ", ".join(_fmt_margin(x) for x in d["opp"])
        rows.append(f"| {disp} | {me_s} | {opp_s} | {_fmt_margin(edge)} |")
    return "\n".join(rows) + "\n"


def render_markdown(data, result, me_name, opp_names, title="GameChanger Scouting Report"):
    summ = result["summary"]
    me = summ.get(me_name, {})
    lines = []
    lines.append(f"# {title}")
    lines.append(f"_Generated {datetime.datetime.now():%Y-%m-%d %H:%M} · "
                 f"{len(data['games'])} games across {len(data['teams'])} teams · "
                 f"home-field ≈ {_fmt_margin(result['home_adv'])} runs_\n")

    # Your team stats — top of page
    lines.append("## Your team\n")
    lines.append(_scouting_card(me))

    # Interactive matchup explorer — the primary projection tool (picker + JS in HTML render)
    lines.append("## Matchup explorer\n")
    lines.append("_Pick an opponent from the tournament field to get the projection, what to "
                 "prepare for, common opponents, and their last 5 games — computed instantly._\n")
    lines.append("[[MATCHUP_EXPLORER]]")

    # Visual charts (replaced with Chart.js canvases in the HTML render)
    lines.append("\n## Power rankings & matchup map\n")
    lines.append("[[POWER_CHART]]")
    lines.append("\n_Offense vs. defense — top-right = strong both sides; "
                 "bottom-left = beatable both sides. Your team is highlighted._\n")
    lines.append("[[OFFDEF_CHART]]")

    # SoS leaderboard among seeds — the "#" rank column renumbers live when you sort
    opp_set = set(opp_names)
    seeds = [(cn, s) for cn, s in summ.items() if s["is_seed"]]
    seeds.sort(key=lambda kv: kv[1]["sos"], reverse=True)
    lines.append("## Strength of schedule (seed teams)\n")
    lines.append("| # | Team | SoS | Power | Offense | Defense | Record |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, (cn, s) in enumerate(seeds, 1):
        if cn == me_name:
            rank = f"<span class='you-row'></span>{i}"
            team = f"**{s['display']}** <span class='youbadge'>you</span>"
        elif cn in opp_set:
            rank = f"<span class='opp-row'></span>{i}"
            team = f"**{s['display']}** <span class='oppbadge'>next opp</span>"
        else:
            rank = str(i)
            team = s['display']
        lines.append(f"| {rank} | {team} | {_sos(s['sos'])} | "
                     f"{_signed(s['massey'])} | {_signed(s['off'])} | "
                     f"{_signed(s['def'])} | {_rec(s['api_record'])} |")

    # Glossary
    lines.append(_glossary())

    # Caveats
    lines.append("\n## Notes & caveats\n")
    lines.append(
        "- Ratings come from a Massey least-squares model on game margins (home-field + "
        "ridge regularization); Elo is a chronological cross-check.\n"
        "- Offense/Defense ratings are a separate opponent-adjusted least-squares split, so "
        "facing weak teams inflates raw runs but not the adjusted numbers.\n"
        "- Only **seed teams** (ids you passed) have full schedules; other teams appear "
        "only via games against the seeds, so their ratings are based on partial data.\n"
        "- Youth results are noisy and team-name matching across feeds is fuzzy — treat "
        "projections as directional. Confidence reflects common-opponent count + head-to-head.\n"
        "- To deepen strength-of-schedule, add more team ids as seeds (see the unresolved "
        "opponents listed by `main.py`).\n"
    )
    return "\n".join(lines) + "\n"


def _glossary():
    return (
        "\n## Glossary\n"
        "| Term | What it means |\n"
        "|---|---|\n"
        "| **Power rating (Massey)** | Overall strength in runs vs. an average team in this pool. "
        "+3 ≈ three runs better than average. Solved by least-squares over every game margin. |\n"
        "| **Elo** | Independent strength score (starts at 1500) updated game-by-game; "
        "a cross-check on Massey. Higher = stronger; ~100 pts ≈ a meaningful gap. |\n"
        "| **Offense (adj)** | Opponent-adjusted runs scored vs. average. +1.5 means they score ~1.5 "
        "runs more than a typical team would against the *same* defenses. |\n"
        "| **Defense (adj)** | Opponent-adjusted runs *prevented* vs. average. **Positive = good defense** "
        "(they allow fewer runs than a typical team would vs. the same offenses). |\n"
        "| **runs scored/allowed per game** | Raw, unadjusted averages — easy to read but flattered or "
        "punished by schedule strength. |\n"
        "| **Strength of schedule (SoS)** | Average power rating of the opponents a team has faced. "
        "Amber = tough slate, blue = soft slate. |\n"
        "| **Projected runs / win prob** | Expected final margin and win chance for your matchup, blending "
        "the rating gap, common opponents, and any head-to-head. |\n"
        "| **Common opponents** | Teams both you and the opponent have played; comparing your margins vs. "
        "theirs controls for schedule. |\n"
        "| **Head-to-head (h2h)** | Games you've played against that opponent directly. |\n"
        "| **Confidence** | How much data backs the projection (common-opponent count + h2h + games played). |\n"
        "| **Home-field** | Estimated run value of playing at home, from the model. |\n"
    )


def render_csv(result):
    rows = ["team,record,win_pct,avg_margin,massey,elo,off_adj,def_adj,rs_pg,ra_pg,sos,is_seed"]
    for s in sorted(result["summary"].values(), key=lambda s: s["massey"], reverse=True):
        rec = _rec(s["api_record"])
        rows.append(f"\"{s['display']}\",{rec},{s['win_pct']:.3f},{s['avg_margin']:.2f},"
                    f"{s['massey']:.2f},{s['elo']:.0f},{s['off']:.2f},{s['def']:.2f},"
                    f"{s['rs_pg']:.2f},{s['ra_pg']:.2f},{s['sos']:.2f},{s['is_seed']}")
    return "\n".join(rows) + "\n"


_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       max-width: 860px; margin: 2rem auto; padding: 0 1.2rem; line-height: 1.5;
       color: #1a1a1a; background: #fff; }
h1 { border-bottom: 3px solid #ff6b00; padding-bottom: .3rem; }
h2 { margin-top: 1.8rem; border-bottom: 1px solid #ddd; padding-bottom: .2rem; }
h3 { margin-top: 1.2rem; color: #c2410c; }
em { color: #666; }
table { border-collapse: collapse; width: 100%; margin: .6rem 0 1.2rem; font-size: .93rem; }
th, td { border: 1px solid #ddd; padding: .4rem .6rem; text-align: left; }
th { background: #fff3e8; }
tr:nth-child(even) td { background: #faf7f4; }
tr.you td { background: #fff3d6; box-shadow: inset 3px 0 0 #ff6b00; font-weight: 600; }
tr.opp td { background: #e3f6f2; box-shadow: inset 3px 0 0 #0d9488; }
.youbadge { background: #ff6b00; color: #fff; font-size: .72rem; font-weight: 700;
            padding: .03rem .42rem; border-radius: 10px; vertical-align: middle; }
.oppbadge { background: #0d9488; color: #fff; font-size: .72rem; font-weight: 700;
            padding: .03rem .42rem; border-radius: 10px; vertical-align: middle; }
code { background: #f2f2f2; padding: .1rem .3rem; border-radius: 3px; }
ul { padding-left: 1.2rem; }
.team { text-decoration: underline; text-underline-offset: 3px; text-decoration-thickness: 2px; }
.stat { font-weight: 700; font-variant-numeric: tabular-nums; }
.stat.good  { color: #15803d; }   /* green  — strong / favorable */
.stat.bad   { color: #b91c1c; }   /* red    — weak / unfavorable */
.stat.neu   { color: #555; }      /* gray   — middle of the pack  */
.stat.tough { color: #c2410c; }   /* amber  — hard schedule       */
.stat.soft  { color: #0369a1; }   /* blue   — soft schedule       */
.chart-wrap { margin: 1rem 0 1.6rem; padding: .8rem 1rem; border: 1px solid #eee;
              border-radius: 8px; background: #fff; }
.chart-wrap canvas { max-width: 100%; }
.replist { list-style: none; padding-left: 0; }
.replist li { padding: .55rem .2rem; border-bottom: 1px solid #eee; display: flex;
              flex-wrap: wrap; align-items: baseline; gap: .2rem .8rem; }
.replist a { font-weight: 600; font-size: 1.05rem; text-decoration: none; color: #c2410c; }
.replist a:hover { text-decoration: underline; }
.gen { color: #888; font-size: .85rem; }
th.sortcol { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortcol:hover { background: #ffe6cf; }
th .arrow { font-size: .8em; color: #ff6b00; }
.mx { border: 1px solid #e3c9b0; border-radius: 8px; padding: .9rem 1.1rem;
      margin: 1rem 0 1.6rem; background: #fffaf5; }
.mx label { font-weight: 600; }
.mx select { font-size: 1rem; padding: .3rem .5rem; margin-left: .4rem; border-radius: 6px;
             border: 1px solid #ccc; background: #fff; color: inherit; }
.mx .proj { font-size: 1.08rem; margin: .8rem 0 .3rem; }
.mx .sig { color: #666; font-size: .9rem; }
.mx h3 { margin-top: 1rem; }
.mx h4 { margin: 1rem 0 .2rem; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #1e1e1e; }
  h2 { border-color: #444; } th { background: #3a2a1a; }
  tr:nth-child(even) td { background: #262626; } code { background: #333; }
  tr.you td { background: #3a2f1a; }
  tr.opp td { background: #16302c; }
  th, td { border-color: #444; }
  .replist li { border-color: #383838; } .replist a { color: #fb923c; }
  .gen { color: #999; }
  th.sortcol:hover { background: #4a3520; } th .arrow { color: #fb923c; }
  .mx { background: #241f1a; border-color: #4a3520; }
  .mx select { background: #2a2a2a; border-color: #555; }
  .mx .sig { color: #aaa; }
  .stat.good { color: #4ade80; } .stat.bad { color: #f87171; }
  .stat.neu { color: #d7dee8; } .stat.tough { color: #fb923c; } .stat.soft { color: #54c1f5; }
  .chart-wrap { background: #242424; border-color: #383838; }
}
"""


def _short(name, n=16):
    return name if len(name) <= n else name[: n - 1] + "…"


# category colors shared by both charts
_C_ME, _C_OPP, _C_OTHER = "#ff6b00", "#0d9488", "#9ca3af"


def _chart_data(result, me_name, opp_names):
    """Build JSON-able data for the power-ranking bar + offense/defense scatter,
    over the seed teams (the ones with full schedules)."""
    summ = result["summary"]
    opp_set = set(opp_names)
    seeds = [(cn, s) for cn, s in summ.items() if s["is_seed"]]

    def color(cn):
        return _C_ME if cn == me_name else (_C_OPP if cn in opp_set else _C_OTHER)

    # power ranking: strongest at top
    seeds_by_power = sorted(seeds, key=lambda kv: kv[1]["massey"], reverse=True)
    power = {
        "labels": [_short(s["display"]) for _, s in seeds_by_power],
        "values": [round(s["massey"], 2) for _, s in seeds_by_power],
        "colors": [color(cn) for cn, _ in seeds_by_power],
    }

    # offense (x) vs defense (y) scatter, grouped for a meaningful legend
    groups = {"You": [], "Opponents": [], "Other seeds": []}
    for cn, s in seeds:
        bucket = "You" if cn == me_name else ("Opponents" if cn in opp_set else "Other seeds")
        groups[bucket].append({"x": round(s["off"], 2), "y": round(s["def"], 2),
                               "label": _short(s["display"], 18)})
    offdef = {"You": groups["You"], "Opponents": groups["Opponents"],
              "Other": groups["Other seeds"]}
    return {"power": power, "offdef": offdef}


def _charts_html(result, me_name, opp_names):
    import json
    d = _chart_data(result, me_name, opp_names)
    power_canvas = "<div class='chart-wrap'><canvas id='powerChart' height='260'></canvas></div>"
    offdef_canvas = "<div class='chart-wrap'><canvas id='offDefChart' height='340'></canvas></div>"
    script = f"""
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<script>
const POWER = {json.dumps(d['power'])};
const OFFDEF = {json.dumps(d['offdef'])};
const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
const grid = dark ? '#3a3a3a' : '#e3e3e3';
const tick = dark ? '#d7dee8' : '#444';
Chart.register(ChartDataLabels);

// --- Power rankings (horizontal bars) ---
new Chart(document.getElementById('powerChart'), {{
  type: 'bar',
  data: {{ labels: POWER.labels,
    datasets: [{{ label: 'Power (runs vs avg)', data: POWER.values,
      backgroundColor: POWER.colors, borderRadius: 4 }}] }},
  options: {{ indexAxis: 'y', responsive: true,
    plugins: {{ legend: {{ display: false }},
      title: {{ display: true, text: 'Power rankings (Massey, runs vs. average)', color: tick }},
      datalabels: {{ anchor: 'end', align: 'end', color: tick,
        formatter: v => (v >= 0 ? '+' : '') + v.toFixed(1) }} }},
    scales: {{ x: {{ grid: {{ color: grid }}, ticks: {{ color: tick }},
        title: {{ display: true, text: 'runs vs. average', color: tick }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: tick }} }} }} }}
}});

// --- Offense vs Defense quadrant scatter ---
const mkPts = (arr, c) => ({{ data: arr, backgroundColor: c, pointRadius: 7,
  pointHoverRadius: 9 }});
// guideline plugin: draw axes at 0,0 to split the four quadrants
const quad = {{ id: 'quad', beforeDraw(c) {{
  const {{ctx, chartArea: a, scales}} = c;
  const x0 = scales.x.getPixelForValue(0), y0 = scales.y.getPixelForValue(0);
  ctx.save(); ctx.strokeStyle = dark ? '#555' : '#bbb'; ctx.setLineDash([5,4]);
  ctx.beginPath(); ctx.moveTo(x0, a.top); ctx.lineTo(x0, a.bottom);
  ctx.moveTo(a.left, y0); ctx.lineTo(a.right, y0); ctx.stroke(); ctx.restore();
}} }};
new Chart(document.getElementById('offDefChart'), {{
  type: 'scatter',
  data: {{ datasets: [
    Object.assign(mkPts(OFFDEF.You, '{_C_ME}'), {{ label: 'You' }}),
    Object.assign(mkPts(OFFDEF.Opponents, '{_C_OPP}'), {{ label: 'Opponents' }}),
    Object.assign(mkPts(OFFDEF.Other, '{_C_OTHER}'), {{ label: 'Other seeds' }}),
  ] }},
  plugins: [quad],
  options: {{ responsive: true,
    plugins: {{ legend: {{ labels: {{ color: tick }} }},
      title: {{ display: true, text: 'Offense vs. Defense (top-right = strong both sides)', color: tick }},
      datalabels: {{ align: 'right', offset: 6, color: tick, font: {{ size: 10 }},
        formatter: (v, ctx) => ctx.dataset.data[ctx.dataIndex].label }},
      tooltip: {{ callbacks: {{ label: c => `${{c.raw.label}}: off ${{c.raw.x}}, def ${{c.raw.y}}` }} }} }},
    scales: {{
      x: {{ grid: {{ color: grid }}, ticks: {{ color: tick }},
        title: {{ display: true, text: 'Offense  →  scores more', color: tick }} }},
      y: {{ grid: {{ color: grid }}, ticks: {{ color: tick }},
        title: {{ display: true, text: 'Defense  →  allows fewer', color: tick }} }} }} }}
}});
</script>
"""
    return power_canvas, offdef_canvas, script


# ---------------------------------------------------------------- matchup explorer
def _explorer_data(result, data, me_name, opp_names):
    """Compact JSON payload so the page can recompute a projection for ANY team
    client-side. Ratings are global (independent of opponent choice), so we only
    need the per-team ratings + the games graph to reproduce project() in JS."""
    summ = result["summary"]
    od = result["off_def"]
    teams = {}
    for cn, s in summ.items():
        teams[cn] = {
            "d": s["display"], "seed": 1 if s["is_seed"] else 0,
            "gp": s["gp"], "wp": round(s["win_pct"], 3), "am": round(s["avg_margin"], 2),
            "ma": round(s["massey"], 2), "elo": round(s["elo"]),
            "off": round(s["off"], 2), "def": round(s["def"], 2),
            "rs": round(s["rs_pg"], 1), "ra": round(s["ra_pg"], 1),
            "sos": round(s["sos"], 2), "l5": s["last5"],
            "rec": _rec(s["api_record"]) if s["api_record"] else f"{s['w']}-{s['l']}-{s['t']}",
        }
    games = [[g["a"], g["b"], g["a_score"], g["b_score"], g.get("date", "")]
             for g in data["games"]
             if g["a"] and g["b"] and not g["a"].startswith("tbd")
             and not g["b"].startswith("tbd")
             and g["a_score"] is not None and g["b_score"] is not None]
    default = next((o for o in opp_names if o), "")
    return {"me": me_name, "mu": round(od["mu"], 3), "sigma": 3.6,
            "def0": default, "teams": teams, "games": games}


# plain JS (no Python interpolation) — GC is injected as a const just above it
_EXPLORER_JS = """
(function () {
  const T = GC.teams, G = GC.games, ME = GC.me, MU = GC.mu, SIGMA = GC.sigma;
  function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function disp(cn){ return esc((T[cn] && T[cn].d) || cn); }
  function fmtM(x){ return (x >= 0 ? '+' : '') + x.toFixed(1); }
  function signed(x, unit, goodHigh){
    unit = unit || ''; if (goodHigh === undefined) goodHigh = true;
    var cls = (x >= 0.8) ? (goodHigh ? 'good' : 'bad')
            : (x <= -0.8) ? (goodHigh ? 'bad' : 'good') : 'neu';
    return "<span class='stat " + cls + "'>" + fmtM(x) + unit + "</span>";
  }
  function pct(p){ var c = p >= 0.55 ? 'good' : (p <= 0.45 ? 'bad' : 'neu');
    return "<span class='stat " + c + "'>" + Math.round(p * 100) + "%</span>"; }
  function sosSpan(x){ var c = x >= 0.4 ? 'tough' : (x <= -0.4 ? 'soft' : 'neu');
    return "<span class='stat " + c + "'>" + fmtM(x) + "</span>"; }
  function label(x){ return x >= 2 ? 'very strong' : x >= 0.8 ? 'strong'
    : x > -0.8 ? 'average' : x > -2 ? 'weak' : 'very weak'; }
  function labelSpan(w){ var c = (w === 'very strong' || w === 'strong') ? 'good'
    : (w === 'weak' || w === 'very weak') ? 'bad' : 'neu';
    return "<span class='stat " + c + "'>" + w + "</span>"; }
  function mean(a){ return a.reduce(function (s, x){ return s + x; }, 0) / a.length; }

  function commonOpps(me, opp){
    var res = {};
    G.forEach(function (g){
      [[g[0], g[1], g[2], g[3]], [g[1], g[0], g[3], g[2]]].forEach(function (p){
        var who = p[0], other = p[1], s = p[2], o = p[3];
        if (who === me) { (res[other] = res[other] || {me: [], opp: []}).me.push(s - o); }
        if (who === opp) { (res[other] = res[other] || {me: [], opp: []}).opp.push(s - o); }
      });
    });
    var common = {};
    Object.keys(res).forEach(function (t){
      if (t === me || t === opp) return;
      if (res[t].me.length && res[t].opp.length) common[t] = res[t];
    });
    return common;
  }
  function h2h(me, opp){
    var out = [];
    G.forEach(function (g){
      if (g[0] === me && g[1] === opp) out.push(g[2] - g[3]);
      else if (g[0] === opp && g[1] === me) out.push(g[3] - g[2]);
    });
    return out;
  }
  function project(opp){
    var me = ME;
    var mm = T[me].ma - T[opp].ma;
    var common = commonOpps(me, opp);
    var edges = Object.keys(common).map(function (t){ return mean(common[t].me) - mean(common[t].opp); });
    var cm = edges.length ? mean(edges) : null;
    var hh = h2h(me, opp);
    var hm = hh.length ? mean(hh) : null;
    var wMass = 1, wCom = Math.min(edges.length, 8) / 8 * 1.5, wH = Math.min(hh.length, 3) * 0.8;
    var num = mm * wMass, den = wMass;
    if (cm !== null) { num += cm * wCom; den += wCom; }
    if (hm !== null) { num += hm * wH; den += wH; }
    var blended = num / den;
    var winp = 1 / (1 + Math.exp(-blended / SIGMA));
    var cc = Object.keys(common).length;
    var confScore = cc + (hh.length ? 2 : 0) + Math.min(T[opp].gp, 6) / 6;
    var conf = confScore >= 5 ? 'moderate' : (confScore >= 3 ? 'low-moderate' : 'low');
    var expRs = Math.max(0, MU + T[me].off - T[opp].def);
    var expRa = Math.max(0, MU + T[opp].off - T[me].def);
    return {mm: mm, cm: cm, hm: hm, blended: blended, winp: winp, cc: cc, conf: conf,
            common: common, h2h: hh, expRs: expRs, expRa: expRa};
  }
  function card(cn){
    var s = T[cn];
    return "<h3>" + disp(cn) + "</h3><ul>"
      + "<li>Record: <b>" + esc(s.rec) + "</b> (win% " + Math.round(s.wp * 100) + "%, last5 " + esc(s.l5) + ")</li>"
      + "<li>Power (Massey): " + signed(s.ma, ' runs') + " &middot; Elo " + s.elo + "</li>"
      + "<li>Offense: " + signed(s.off, ' runs') + " adj &middot; " + s.rs.toFixed(1) + " runs scored/game</li>"
      + "<li>Defense: " + signed(s.def, ' runs') + " adj &middot; " + s.ra.toFixed(1) + " runs allowed/game</li>"
      + "<li>Strength of schedule: " + sosSpan(s.sos) + " &middot; Avg margin: " + signed(s.am, ' runs') + " over " + s.gp + " games</li>"
      + "</ul>";
  }
  function commonTable(common){
    var keys = Object.keys(common);
    if (!keys.length) return "<p><em>No common opponents found in the data.</em></p>";
    keys.sort(function (a, b){
      return (mean(common[b].me) - mean(common[b].opp)) - (mean(common[a].me) - mean(common[a].opp));
    });
    var rows = "<table><thead><tr><th>Common opponent</th><th>Your result(s)</th>"
      + "<th>Their result(s)</th><th>Edge</th></tr></thead><tbody>";
    keys.forEach(function (t){
      var d = common[t], edge = mean(d.me) - mean(d.opp);
      rows += "<tr><td>" + disp(t) + "</td><td>" + d.me.map(fmtM).join(', ')
        + "</td><td>" + d.opp.map(fmtM).join(', ') + "</td><td>" + signed(edge) + "</td></tr>";
    });
    return rows + "</tbody></table>";
  }
  function last5Table(opp){
    var gs = [];
    G.forEach(function (g){
      var date = g[4] || "";
      if (g[0] === opp) gs.push({date: date, other: g[1], ts: g[2], os: g[3]});
      else if (g[1] === opp) gs.push({date: date, other: g[0], ts: g[3], os: g[2]});
    });
    gs.sort(function (a, b){ return a.date < b.date ? 1 : (a.date > b.date ? -1 : 0); });
    gs = gs.slice(0, 5);
    if (!gs.length) return "<p><em>No recent games in the data.</em></p>";
    var rows = "<table><thead><tr><th>Date</th><th>Opponent</th><th>Score</th>"
      + "<th>Result</th></tr></thead><tbody>";
    gs.forEach(function (g){
      var res = g.ts > g.os ? "W" : (g.ts < g.os ? "L" : "T");
      var cls = res === "W" ? "good" : (res === "L" ? "bad" : "neu");
      rows += "<tr><td>" + esc(g.date || "—") + "</td><td>" + disp(g.other) + "</td><td>"
        + g.ts + "&ndash;" + g.os + "</td><td><span class='stat " + cls + "'>" + res + "</span></td></tr>";
    });
    return rows + "</tbody></table>";
  }
  function render(opp){
    var p = project(opp);
    var verdict = p.blended > 0 ? 'you favored' : 'opponent favored';
    var h = "";
    h += "<p class='proj'><b>vs <span class='team'>" + disp(opp) + "</span></b> &mdash; projected "
      + signed(p.blended, ' runs') + " (" + verdict + "), win prob " + pct(p.winp)
      + " &middot; confidence: <em>" + p.conf + "</em></p>";
    h += "<p><b>Prepare for:</b> their offense is " + labelSpan(label(T[opp].off)) + " ("
      + signed(T[opp].off) + " adj) &mdash; likely to score ~<b>" + Math.round(p.expRa) + "</b> on you; "
      + "their defense is " + labelSpan(label(T[opp].def)) + " (" + signed(T[opp].def)
      + " adj) &mdash; you should put up ~<b>" + Math.round(p.expRs) + "</b>.</p>";
    h += "<p class='sig'>signals: rating gap " + fmtM(p.mm)
      + (p.cm !== null ? " &middot; common-opp " + fmtM(p.cm) : "")
      + (p.hm !== null ? " &middot; head-to-head " + fmtM(p.hm) : "")
      + " (" + p.cc + " common opponents)</p>";
    h += card(opp);
    h += "<h4>Common opponents vs you</h4>" + commonTable(p.common);
    h += "<h4>" + disp(opp) + " &mdash; last 5 games</h4>" + last5Table(opp);
    document.getElementById('mx-out').innerHTML = h;
  }
  var sel = document.getElementById('mx-pick');
  if (!sel) return;
  Object.keys(T).filter(function (cn){ return cn !== ME && T[cn].seed; })
    .sort(function (a, b){ return T[a].d.localeCompare(T[b].d); })
    .forEach(function (cn){
      var o = document.createElement('option');
      o.value = cn; o.textContent = T[cn].d; sel.appendChild(o);
    });
  sel.addEventListener('change', function (){ if (sel.value) render(sel.value); });
  if (sel.options.length) {
    var d0 = GC.def0;
    var has = Array.prototype.some.call(sel.options, function (o){ return o.value === d0; });
    sel.value = has ? d0 : sel.options[0].value;
    render(sel.value);
  }
})();
"""


def _explorer_html(result, data, me_name, opp_names):
    import json
    payload = json.dumps(_explorer_data(result, data, me_name, opp_names))
    container = ("<div class='mx'><label for='mx-pick'>Pick your next opponent:</label>"
                 "<select id='mx-pick'></select>"
                 "<div id='mx-out'></div></div>")
    script = "<script>\nconst GC = " + payload + ";\n" + _EXPLORER_JS + "\n</script>"
    return container, script


_SORT_SCRIPT = """
<script>
(function () {
  function num(cell) {
    var n = parseFloat((cell.textContent || "").replace(/[^0-9.+-]/g, ""));
    return isNaN(n) ? null : n;
  }
  function sortTable(tbl, col, th) {
    var body = tbl.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    var numeric = rows.every(function (r) {
      var c = r.cells[col]; return !c || c.textContent.trim() === "" || num(c) !== null;
    });
    var dir = th.getAttribute("data-dir") === "desc" ? "asc" : "desc";
    var heads = tbl.tHead.rows[0].cells;
    for (var h = 0; h < heads.length; h++) {
      heads[h].removeAttribute("data-dir");
      var old = heads[h].querySelector(".arrow"); if (old) old.remove();
    }
    th.setAttribute("data-dir", dir);
    var arrow = document.createElement("span");
    arrow.className = "arrow";
    arrow.textContent = dir === "asc" ? " \\u25B2" : " \\u25BC";
    th.appendChild(arrow);
    rows.sort(function (a, b) {
      var ca = a.cells[col], cb = b.cells[col], cmp;
      if (numeric) {
        var na = num(ca), nb = num(cb);
        na = na === null ? -Infinity : na; nb = nb === null ? -Infinity : nb;
        cmp = na - nb;
      } else {
        cmp = (ca.textContent || "").trim().localeCompare((cb.textContent || "").trim());
      }
      return dir === "asc" ? cmp : -cmp;
    });
    rows.forEach(function (r) { body.appendChild(r); });
    renumber(tbl);
  }
  function renumber(tbl) {
    var heads = tbl.tHead.rows[0].cells, rc = -1;
    for (var i = 0; i < heads.length; i++) {
      if (heads[i].textContent.trim() === "#") { rc = i; break; }
    }
    if (rc < 0) return;
    var rows = tbl.tBodies[0].rows;
    for (var r = 0; r < rows.length; r++) {
      if (rows[r].cells[rc]) rows[r].cells[rc].textContent = (r + 1);
    }
  }
  document.querySelectorAll("table").forEach(function (tbl) {
    if (!tbl.tHead) return;
    var heads = Array.prototype.slice.call(tbl.tHead.rows[0].cells);
    var isSoS = heads.some(function (th) {
      return /^(SoS|Power|Offense|Defense)$/i.test(th.textContent.trim());
    });
    if (!isSoS) return;
    heads.forEach(function (th, i) {
      if (th.textContent.trim() === "#") return;   // rank column isn't sortable
      th.classList.add("sortcol");
      th.title = "Click to sort";
      th.addEventListener("click", function () { sortTable(tbl, i, th); });
    });
    renumber(tbl);
  });
})();
</script>
"""


def render_html(md_text, result, me_name, opp_names, data=None, title="GC Scouting Report"):
    import re
    import markdown
    body = markdown.markdown(md_text, extensions=["tables", "sane_lists"])
    # promote the marked SoS row to a highlighted <tr class='you'>
    body = re.sub(r"<tr>\s*<td><span class='you-row'></span>", "<tr class='you'><td>", body)
    body = re.sub(r"<tr>\s*<td><span class='opp-row'></span>", "<tr class='opp'><td>", body)
    power_canvas, offdef_canvas, script = _charts_html(result, me_name, opp_names)
    # markdown wraps a lone sentinel line in <p>…</p>; swap those for the canvases
    body = body.replace("<p>[[POWER_CHART]]</p>", power_canvas)
    body = body.replace("<p>[[OFFDEF_CHART]]</p>", offdef_canvas)
    # interactive matchup explorer (needs the games graph from `data`)
    explorer_script = ""
    if data is not None:
        container, explorer_script = _explorer_html(result, data, me_name, opp_names)
        body = body.replace("<p>[[MATCHUP_EXPLORER]]</p>", container)
    else:
        body = body.replace("<p>[[MATCHUP_EXPLORER]]</p>", "")
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
            f"<body>{body}{script}{explorer_script}{_SORT_SCRIPT}</body></html>")


def render_index(entries, heading="8U Scouting Reports"):
    """Landing page for GitHub Pages listing every published report (newest first).
    entries: list of {slug, title, generated}."""
    items = []
    for e in entries:
        items.append(
            f"<li><a href='r/{html.escape(e['slug'])}.html'>{html.escape(e['title'])}</a>"
            f"<span class='gen'>generated {html.escape(e.get('generated',''))}</span></li>")
    listing = ("<ul class='replist'>" + "".join(items) + "</ul>") if items \
        else "<p><em>No reports published yet.</em></p>"
    body = (f"<h1>{html.escape(heading)}</h1>"
            f"<p>Youth softball scouting reports generated from public GameChanger data. "
            f"Newest first.</p>{listing}")
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(heading)}</title><style>{_CSS}</style></head>"
            f"<body>{body}</body></html>")
