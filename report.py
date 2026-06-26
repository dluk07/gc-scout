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

    # Headline projections
    lines.append("## Saturday matchup projection\n")
    lines.append(f"Your team: **<span class='team'>{me.get('display', me_name)}</span>** "
                 f"(rating {_signed(me.get('massey',0))})\n")
    for p in result["projections"]:
        o = summ.get(p["opp"], {})
        verdict = "you favored" if p["exp_margin"] > 0 else "opponent favored"
        bits = [f"rating gap {_fmt_margin(p['massey_margin'])}"]
        if p["common_margin"] is not None:
            bits.append(f"common-opp {_fmt_margin(p['common_margin'])}")
        if p["h2h_margin"] is not None:
            bits.append(f"head-to-head {_fmt_margin(p['h2h_margin'])}")
        m = p["matchup"]
        lines.append(
            f"- **vs <span class='team'>{o.get('display', p['opp'])}</span>** — projected "
            f"{_signed(p['exp_margin'], ' runs')} ({verdict}), win prob {_pct(p['win_pct'])} "
            f"· confidence: _{p['confidence']}_\n"
            f"    - **Prepare for:** their offense is {_label_span(m['opp_off_label'])} "
            f"({_signed(m['opp_off'])} adj) — likely to score ~**{m['exp_ra']:.0f}** on you; "
            f"their defense is {_label_span(m['opp_def_label'])} "
            f"({_signed(m['opp_def'])} adj) — you should put up ~**{m['exp_rs']:.0f}**.\n"
            f"    - signals: {' · '.join(bits)}  ({p['n_common']} common opponents)"
        )
    # which is tougher
    if len(result["projections"]) >= 2:
        tough = min(result["projections"], key=lambda p: p["exp_margin"])
        lines.append(f"\n**Tougher draw:** {summ.get(tough['opp'],{}).get('display', tough['opp'])} "
                     f"(lowest projected margin for you).\n")

    # Visual charts (replaced with Chart.js canvases in the HTML render)
    lines.append("\n## Power rankings & matchup map\n")
    lines.append("[[POWER_CHART]]")
    lines.append("\n_Offense vs. defense — top-right = strong both sides; "
                 "bottom-left = beatable both sides. Your team is highlighted._\n")
    lines.append("[[OFFDEF_CHART]]")

    # Scouting cards
    lines.append("\n## Scouting cards\n")
    lines.append(_scouting_card(me))
    for p in result["projections"]:
        o = summ.get(p["opp"])
        if o:
            lines.append(_scouting_card(o))
            lines.append(f"**Common opponents vs you:**\n")
            lines.append(_common_table(p["common"], summ))

    # SoS leaderboard among seeds
    opp_set = set(opp_names)
    seeds = [(cn, s) for cn, s in summ.items() if s["is_seed"]]
    seeds.sort(key=lambda kv: kv[1]["sos"], reverse=True)
    lines.append("## Strength of schedule (seed teams)\n")
    lines.append("| Team | SoS | Power | Offense | Defense | Record |")
    lines.append("|---|---|---|---|---|---|")
    for cn, s in seeds:
        if cn == me_name:
            name = (f"<span class='you-row'></span>**{s['display']}** "
                    f"<span class='youbadge'>you</span>")
        elif cn in opp_set:
            name = (f"<span class='opp-row'></span>**{s['display']}** "
                    f"<span class='oppbadge'>next opp</span>")
        else:
            name = s['display']
        lines.append(f"| {name} | {_sos(s['sos'])} | "
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
  }
  document.querySelectorAll("table").forEach(function (tbl) {
    if (!tbl.tHead) return;
    var heads = Array.prototype.slice.call(tbl.tHead.rows[0].cells);
    var isSoS = heads.some(function (th) {
      return /^(SoS|Power|Offense|Defense)$/i.test(th.textContent.trim());
    });
    if (!isSoS) return;
    heads.forEach(function (th, i) {
      th.classList.add("sortcol");
      th.title = "Click to sort";
      th.addEventListener("click", function () { sortTable(tbl, i, th); });
    });
  });
})();
</script>
"""


def render_html(md_text, result, me_name, opp_names, title="GC Scouting Report"):
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
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
            f"<body>{body}{script}{_SORT_SCRIPT}</body></html>")


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
