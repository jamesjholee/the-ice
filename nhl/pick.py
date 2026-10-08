"""Log a pick against today's board.

python -m nhl.pick --date 2026-10-08 --player "Reinhart" --market goal --odds +150 --stake 1
python -m nhl.pick --date 2026-10-08 --player "Thompson" --market sog3 --odds -120
"""
import argparse, csv, sys

from .features import implied
from .store import add_pick

MARKETS = {"goal": "p_goal", "sog2": "p_sog2", "sog3": "p_sog3", "sog4": "p_sog4"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--player", required=True, help="substring of the player name on board.csv")
    ap.add_argument("--market", choices=MARKETS, required=True)
    ap.add_argument("--odds", required=True, help="American odds, e.g. +150 or -120")
    ap.add_argument("--stake", type=float, default=1.0)
    ap.add_argument("--note", default="")
    ap.add_argument("--board", default="board.csv")
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(a.board)) if a.player.lower() in r["name"].lower()]
    if len(rows) != 1:
        print(f"{len(rows)} matches for '{a.player}':", [r["name"] for r in rows], file=sys.stderr); sys.exit(1)
    r = rows[0]
    line = {"goal": 0.5, "sog2": 1.5, "sog3": 2.5, "sog4": 3.5}[a.market]
    mp, bp = float(r[MARKETS[a.market]]), implied(a.odds)
    add_pick(a.date, int(r["pid"]), r["name"], r["team"], r["opp"], a.market, line,
             int(a.odds.replace("+", "")), a.stake, mp, bp, a.note)
    print(f"logged {r['name']} {a.market} over {line} @ {a.odds}  model {mp:.3f} vs book {bp:.3f} "
          f"edge {100*(mp-bp):+.1f} pts")


if __name__ == "__main__":
    main()
