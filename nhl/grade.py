"""Grade ungraded picks from final boxscores and print the running record.

python -m nhl.grade                 # grades every ungraded pick whose game is final
python -m nhl.grade --date 2026-10-07
"""
import argparse
from datetime import date

from .data import games_on, boxscore
from .features import payout
from .store import ungraded, grade, record
from .parlays import grade_parlays, record as parlay_record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    a = ap.parse_args()
    picks = ungraded(a.date)
    if not picks:
        print("nothing to grade")
    by_date = {}
    for p in picks:
        by_date.setdefault(p[1], []).append(p)
    for d, ps in by_date.items():
        stats = {}
        for g in games_on(date.fromisoformat(d)):
            sk, _ = boxscore(g["id"])
            for r in sk:
                stats[r["pid"]] = r
        for (pid_, dt, pid, name, team, opp, market, line, odds, stake, mp, bp) in ps:
            r = stats.get(pid)
            if r is None:
                # game final but player absent => scratched/injured: void the pick (0 P&L)
                if any(s["team"] in (team, opp) for s in stats.values()):
                    grade(pid_, 0, 0.0); print(f"  {dt} {name}: did not play — voided")
                else:
                    print(f"  {dt} {name}: game not final (left ungraded)")
                continue
            val = r["goals"] if market == "goal" else r["sog"]
            hit = 1 if val > line else 0
            pnl = payout(odds, stake) if hit else -stake
            grade(pid_, hit, pnl)
            print(f"  {dt} {name:<22}{market:<5} o{line}  {'G' if market=='goal' else 'SOG'}={val}  "
                  f"{'HIT ' if hit else 'MISS'} {pnl:+.2f}u  (model {mp:.2f} book {bp:.2f})")
    # parlays: collect stats for every date with ungraded tickets
    from .parlays import _read as read_parlays
    pdates = {r["date"] for r in read_parlays() if r.get("result", "") == ""}
    sbd = {}
    for dstr in pdates:
        st = {}
        for g in games_on(date.fromisoformat(dstr)):
            sk, _ = boxscore(g["id"])
            for r in sk:
                st[r["pid"]] = r
        if st:
            sbd[dstr] = st
    n = grade_parlays(sbd)
    if n:
        print(f"graded {n} parlay tickets")
    pr = parlay_record()
    if pr:
        print("\n=== Parlays ===")
        for k, (cnt, hits, pnl) in sorted(pr["by"].items()):
            print(f"{k:<8} {hits}/{cnt}  P&L {pnl:+.2f}u")
        print(f"TOTAL    {pr['total'][1]}/{pr['total'][0]}  P&L {pr['total'][2]:+.2f}u")
    rows, tot = record()
    print("\n=== Record ===")
    for m, n, hits, pnl, stake, amp, abp in rows:
        print(f"{m:<6} {hits}/{n} ({hits/n:.1%})  P&L {pnl:+.2f}u on {stake:.1f}u  ROI {pnl/stake:+.1%}  "
              f"avg model {amp:.3f} vs book {abp:.3f}")
    if tot and tot[0]:
        print(f"TOTAL  {tot[1]}/{tot[0]} ({tot[1]/tot[0]:.1%})  P&L {tot[2]:+.2f}u on {tot[3]:.1f}u  ROI {tot[2]/tot[3]:+.1%}")


if __name__ == "__main__":
    main()
