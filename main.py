"""
main.py — CLI for gc-scout.

Pull public GameChanger data for your team + candidate opponents, compute strength of
schedule and a matchup projection, and write a Markdown + CSV + charted HTML report.

You can supply teams two ways:

  1. A teams file (recommended) — list each team's web.gc.com URL with a role prefix:
         python main.py --teams teams.txt
     See teams.example.txt for the format (me / opp / extra + URL or 12-char id).

  2. Inline short ids (the 12-char id from a web.gc.com/teams/<id>/... URL):
         python main.py --me 9rpA1Riw3pSY --opponents U3SbqWb4YPke,BUZ2EzE23lWB
         python main.py --me <id> --opponents <id1>,<id2> --extra <id3>,<id4> --refresh

Each run asks you to name the report (or pass --name). With --publish, the report is
added to docs/ and the GitHub Pages index (docs/index.html) is rebuilt to list them all.
"""
import re
import sys
import json
import argparse
import datetime
from pathlib import Path

import crawl
import analyze
import report

try:                                  # Windows console is cp1252; team names/glyphs need utf-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
PAGES_BASE = "https://dluk07.github.io/gc-scout"

ID = r"[A-Za-z0-9]{12}"
TEAMS_URL_RE = re.compile(r"/teams/(" + ID + r")")
BARE_ID_RE = re.compile(r"^" + ID + r"$")
# section headers (any line with no team id) set the role for the URLs beneath them
SECTION_ALIASES = {
    "me": "me", "my": "me", "my team": "me", "myteam": "me", "home": "me",
    "team": "me", "us": "me", "our team": "me",
    "opp": "opp", "opps": "opp", "opponent": "opp", "opponents": "opp",
    "vs": "opp", "next": "opp", "next opponent": "opp", "next opponents": "opp",
    "seed": "extra", "seeds": "extra", "extra": "extra", "extras": "extra",
    "sos": "extra", "other": "extra", "other teams": "extra",
}


def _canon_for(data, short_id):
    for cn, info in data["teams"].items():
        if info.get("short_id") == short_id:
            return cn
    return None


def extract_id(text):
    """Pull a 12-char GameChanger short id out of a web.gc.com URL or a bare id."""
    if not text:
        return None
    m = TEAMS_URL_RE.search(text)
    if m:
        return m.group(1)
    tok = text.strip()
    return tok if BARE_ID_RE.match(tok) else None


def _section_role(header):
    """Map a section-header line (e.g. 'my team:', 'opponent:', 'seed:') to a role."""
    h = re.sub(r"\s+", " ", header.strip().rstrip(":").strip().lower())
    return SECTION_ALIASES.get(h)


def parse_teams_file(path):
    """Parse a teams file written as labeled sections, e.g.

        my team:
        https://web.gc.com/teams/oAa7MJ7B2N1x

        opponent:
        https://web.gc.com/teams/tmRJRFHZgPDa

        seed:
        https://web.gc.com/teams/4UMPZp88k64i
        ...

    A line with a team id (URL or bare 12-char id) is a team in the current section;
    any other line is a header that switches the section. Returns
    (me_id, [opp_ids], [extra_ids]) with me/opps removed from extras."""
    me, opps, extra = None, [], []
    role = None
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tid = extract_id(line)
        if tid is None:                      # header line → switch section
            role = _section_role(line)
            if role is None:
                print(f"  ! teams file line {n}: unrecognized header {line!r} "
                      f"(use 'my team:', 'opponent:', or 'seed:')")
            continue
        if role == "me":
            if me and me != tid:
                print(f"  ! teams file line {n}: second 'my team' id, using the latest")
            me = tid
        elif role == "opp":
            opps.append(tid)
        elif role == "extra":
            extra.append(tid)
        else:                                # team id before any header
            print(f"  ! teams file line {n}: team listed before any section header, "
                  f"treating as a seed: {line}")
            extra.append(tid)
    opps = list(dict.fromkeys(opps))
    extra = [e for e in dict.fromkeys(extra) if e != me and e not in opps]
    return me, opps, extra


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "report"


def resolve_name(args):
    """Report name: --name wins; otherwise prompt (if interactive); else a dated default."""
    if args.name:
        return args.name.strip()
    if sys.stdin.isatty():
        try:
            n = input("Name this report (e.g. \"8U Scouting Report for 6/27 10:30am\"): ").strip()
            if n:
                return n
        except EOFError:
            pass
    return f"8U Scouting Report {datetime.datetime.now():%Y-%m-%d %H:%M}"


def publish(slug, title, html_text):
    """Write docs/r/<slug>.html, update the manifest, and rebuild docs/index.html."""
    (DOCS / "r").mkdir(parents=True, exist_ok=True)
    report_path = DOCS / "r" / f"{slug}.html"
    report_path.write_text(html_text, encoding="utf-8")

    manifest = DOCS / "reports.json"
    entries = []
    if manifest.exists():
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError:
            entries = []
    now = datetime.datetime.now()
    entries = [e for e in entries if e.get("slug") != slug]   # replace same-slug
    entries.append({"slug": slug, "title": title,
                    "generated": f"{now:%Y-%m-%d %H:%M}", "ts": now.isoformat()})
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    manifest.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    (DOCS / "index.html").write_text(report.render_index(entries), encoding="utf-8")
    return report_path


def delete_report(ident):
    """Remove a published report (matched by slug or name) and rebuild the index."""
    manifest = DOCS / "reports.json"
    if not manifest.exists():
        sys.exit("No docs/reports.json — nothing to delete.")
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    key = slugify(ident)
    matched = [e for e in entries
               if e.get("slug") in (ident, key) or slugify(e.get("title", "")) == key]
    if not matched:
        have = ", ".join(e["slug"] for e in entries) or "(none)"
        sys.exit(f"No published report matching {ident!r}.\nPublished slugs: {have}")
    remaining = [e for e in entries if e not in matched]
    for e in matched:
        f = DOCS / "r" / f"{e['slug']}.html"
        if f.exists():
            f.unlink()
    remaining.sort(key=lambda e: e.get("ts", ""), reverse=True)
    manifest.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
    (DOCS / "index.html").write_text(report.render_index(remaining), encoding="utf-8")
    for e in matched:
        print(f"Deleted: {e['title']}  (r/{e['slug']}.html)")
    print(f"Index now lists {len(remaining)} report(s).")


def main():
    ap = argparse.ArgumentParser(description="GameChanger strength-of-schedule & matchup scout")
    ap.add_argument("--teams", help="path to a teams file (role + URL/id per line); "
                                     "see teams.example.txt")
    ap.add_argument("--me", help="your team short id or web.gc.com URL")
    ap.add_argument("--opponents", default="",
                    help="comma-separated candidate opponent short ids/URLs")
    ap.add_argument("--extra", default="",
                    help="comma-separated extra team ids/URLs to deepen SoS (optional)")
    ap.add_argument("--name", default="", help="report name (otherwise you'll be prompted)")
    ap.add_argument("--refresh", action="store_true", help="ignore cache, refetch")
    ap.add_argument("--publish", action="store_true",
                    help="add to docs/ and rebuild the GitHub Pages index")
    ap.add_argument("--delete", default="",
                    help="delete a published report (by name or slug), rebuild the index, and exit")
    ap.add_argument("--no-open", action="store_true", help="don't auto-open the HTML report")
    args = ap.parse_args()

    if args.delete:
        delete_report(args.delete)
        return

    # --- resolve teams from a file or inline flags ---
    if args.teams:
        me, opps, extra = parse_teams_file(args.teams)
    else:
        me = extract_id(args.me) if args.me else None
        opps = [extract_id(x) for x in args.opponents.split(",") if x.strip()]
        extra = [extract_id(x) for x in args.extra.split(",") if x.strip()]
    if not me:
        sys.exit("ERROR: no 'me' team. Pass --teams <file> (with a `me` line) or --me <id>.")
    opps = [o for o in opps if o]
    extra = [e for e in extra if e]
    if not opps:
        print("WARNING: no opponents given — report will have ratings/SoS but no matchup.")

    # --- name the report up front (so a long fetch doesn't block the prompt) ---
    name = resolve_name(args)
    slug = slugify(name)

    seeds = [me] + opps + extra
    print(f"[gc-scout] \"{name}\"  ->  collecting {len(set(seeds))} teams...")
    data = crawl.collect(seeds, refresh=args.refresh)

    me_name = _canon_for(data, me)
    opp_names = [_canon_for(data, o) for o in opps]
    if not me_name or any(n is None for n in opp_names):
        sys.exit("ERROR: could not resolve one or more team ids (fetch failed?). "
                 "Check the ids/URLs and your network.")

    result = analyze.analyze(data, me_name, opp_names)

    # console summary
    print("\n=== Projection ===")
    summ = result["summary"]
    print(f"You: {summ[me_name]['display']}  (power {summ[me_name]['massey']:+.1f})")
    for p in result["projections"]:
        o = summ.get(p["opp"], {})
        m = p["matchup"]
        print(f"  vs {o.get('display', p['opp']):28s} "
              f"proj {p['exp_margin']:+.1f} runs, win {p['win_pct']*100:.0f}%  "
              f"[{p['confidence']}, {p['n_common']} common]")
        print(f"       their O: {m['opp_off_label']:11s} ({m['opp_off']:+.1f}) ~{m['exp_ra']:.0f} on you"
              f"  |  their D: {m['opp_def_label']:11s} ({m['opp_def']:+.1f}) you ~{m['exp_rs']:.0f}")

    # unresolved opponents (so user can deepen)
    unresolved = sorted({t["display"] for cn, t in data["teams"].items()
                         if not t["is_seed"] and not cn.startswith("tbd")})
    if unresolved:
        print(f"\n{len(unresolved)} non-seed opponents (add their URLs as `extra` to deepen SoS).")

    # write outputs (filenames follow the report slug so they're clearly named)
    REPORTS.mkdir(exist_ok=True)
    md_path = REPORTS / f"{slug}.md"
    csv_path = REPORTS / f"{slug}.csv"
    html_path = REPORTS / f"{slug}.html"
    md_text = report.render_markdown(data, result, me_name, opp_names, title=name)
    md_path.write_text(md_text, encoding="utf-8")
    csv_path.write_text(report.render_csv(result), encoding="utf-8")
    html_text = report.render_html(md_text, result, me_name, opp_names, title=name)
    html_path.write_text(html_text, encoding="utf-8")
    print(f"\nWrote:\n  {html_path}\n  {md_path}\n  {csv_path}")

    if args.publish:
        publish(slug, name, html_text)
        print(f"  published -> {PAGES_BASE}/r/{slug}.html\n  index     -> {PAGES_BASE}/")

    if not args.no_open:
        import webbrowser
        webbrowser.open(html_path.resolve().as_uri())
        print("(opened the HTML report in your browser)")


if __name__ == "__main__":
    main()
