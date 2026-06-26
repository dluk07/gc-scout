"""
main.py — CLI for gc-scout.

Pull public GameChanger data for your team + candidate opponents, compute strength of
schedule and a matchup projection, and write a Markdown scouting report + CSV.

Team ids are the 12-char short ids from a web.gc.com/teams/<id>/... URL.

    python main.py --me 9rpA1Riw3pSY --opponents U3SbqWb4YPke,BUZ2EzE23lWB
    python main.py --me <id> --opponents <id1>,<id2> --refresh

Add more --opponents (or --extra) ids to deepen strength-of-schedule coverage.
"""
import sys
import argparse
import datetime
from pathlib import Path

import crawl
import analyze
import report

REPORTS = Path(__file__).parent / "reports"


def _canon_for(data, short_id):
    for cn, info in data["teams"].items():
        if info.get("short_id") == short_id:
            return cn
    return None


def main():
    ap = argparse.ArgumentParser(description="GameChanger strength-of-schedule & matchup scout")
    ap.add_argument("--me", required=True, help="your team short id (from web.gc.com URL)")
    ap.add_argument("--opponents", required=True,
                    help="comma-separated candidate opponent short ids")
    ap.add_argument("--extra", default="",
                    help="comma-separated extra team ids to deepen SoS (optional)")
    ap.add_argument("--refresh", action="store_true", help="ignore cache, refetch")
    ap.add_argument("--out", default="", help="output basename (default: dated)")
    ap.add_argument("--publish", action="store_true",
                    help="also copy the HTML report to docs/index.html (for GitHub Pages)")
    ap.add_argument("--no-open", action="store_true", help="don't auto-open the HTML report")
    args = ap.parse_args()

    me = args.me.strip()
    opps = [x.strip() for x in args.opponents.split(",") if x.strip()]
    extra = [x.strip() for x in args.extra.split(",") if x.strip()]
    seeds = [me] + opps + extra

    print(f"[gc-scout] collecting {len(seeds)} teams...")
    data = crawl.collect(seeds, refresh=args.refresh)

    me_name = _canon_for(data, me)
    opp_names = [_canon_for(data, o) for o in opps]
    if not me_name or any(n is None for n in opp_names):
        print("ERROR: could not resolve one or more team ids (fetch failed?). "
              "Check the ids and your network/token.")
        sys.exit(1)

    result = analyze.analyze(data, me_name, opp_names)

    # console summary
    print("\n=== Projection ===")
    summ = result["summary"]
    print(f"You: {summ[me_name]['display']}  (power {result['summary'][me_name]['massey']:+.1f})")
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
        print(f"\n{len(unresolved)} non-seed opponents (add their ids as --extra to deepen SoS).")

    # write outputs
    REPORTS.mkdir(exist_ok=True)
    base = args.out or f"scouting_{datetime.date.today().isoformat()}"
    md_path = REPORTS / f"{base}.md"
    csv_path = REPORTS / f"{base}.csv"
    html_path = REPORTS / f"{base}.html"
    md_text = report.render_markdown(data, result, me_name, opp_names)
    md_path.write_text(md_text, encoding="utf-8")
    csv_path.write_text(report.render_csv(result), encoding="utf-8")
    html = report.render_html(md_text, result, me_name, opp_names)
    html_path.write_text(html, encoding="utf-8")
    print(f"\nWrote:\n  {html_path}\n  {md_path}\n  {csv_path}")

    if args.publish:
        docs = Path(__file__).parent / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "index.html").write_text(html, encoding="utf-8")
        print(f"  {docs / 'index.html'}  (published for GitHub Pages)")

    if not args.no_open:
        import webbrowser
        webbrowser.open(html_path.resolve().as_uri())
        print("(opened the HTML report in your browser)")


if __name__ == "__main__":
    main()
