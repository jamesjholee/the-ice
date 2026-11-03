"""Score a slate, join book prices, auto-log model picks, write the board.

python -m nhl.board --out docs                 # today
python -m nhl.board --out docs --auto-pick     # also append model picks to picks.csv (the 6pm Action run)
python -m nhl.board --goalie LAK=Kuemper       # override projected starter (lineup-context column only)

Book prices come from <out>/odds.json if present (written by `python -m nhl.odds`).
"""
import argparse, csv, json, os, sys
from datetime import date, datetime, timezone, timedelta

from .data import games_on, roster, dressed
from .features import load_model, p_goal, p_sog_at_least, american, implied
from .history import build_history
from .odds import norm, best
from .store import add_pick, _read as read_picks

MARKETS = [("goal", "Anytime goal", "p_goal"), ("sog2", "2+ shots", "p_sog2"),
           ("sog3", "3+ shots", "p_sog3"), ("sog4", "4+ shots", "p_sog4")]
# auto-pick thresholds: model minus book implied, in probability points
EDGE_BAR = {"goal": 0.06, "sog2": 0.05, "sog3": 0.04, "sog4": 0.04}
MAX_AUTO_PICKS = 8


def score_slate(d, overrides, min_games):
    model = load_model()
    hist = build_history(d)
    games = games_on(d, final_only=False)
    rows = []
    # last game each team played before today (for "did he dress last game?")
    team_last = {}
    for t, lst in hist.team_sa.items():
        pass
    for pid, h in hist.sk.items():
        if h:
            t = h[-1]["team"]; dt = h[-1]["date"]
            if dt and (t not in team_last or dt > team_last[t]):
                team_last[t] = dt
    for g in games:
        lineup = dressed(g["id"])          # None until the lineup is submitted
        for team, opp in ((g["home"], g["away"]), (g["away"], g["home"])):
            gpid = overrides.get(opp) or hist.likely_starter(opp)
            gname = hist.names.get(gpid, "?") if gpid else "?"
            gsv = hist.goalie_sv(gpid) if gpid else 0.905
            try:
                ros = roster(team)
            except Exception as e:
                print("[roster]", team, e, file=sys.stderr); continue
            for p in ros:
                f = hist.skater_feats(p["pid"], opp_goalie_pid=gpid, min_games=min_games, opp_team=opp)
                if not f:
                    continue
                pg = p_goal(f, model)
                # status: IN (confirmed in lineup) / OUT (lineup up, not in it) /
                #         ? (no lineup yet; didn't play team's last game) / "" (no lineup yet; played last game)
                if lineup is not None:
                    status = "IN" if p["pid"] in lineup else "OUT"
                else:
                    status = "" if f.get("last_date") == team_last.get(team) else "?"
                rows.append(dict(
                    status=status,
                    pid=p["pid"], name=hist.names.get(p["pid"], p["name"]), full_name=p["name"],
                    team=team, opp=opp, pos=p["pos"], game=f"{g['away']}@{g['home']}", start=g.get("start") or "",
                    opp_goalie=gname, opp_gsv=round(gsv, 3),
                    opp_sa=round(f["opp_sa"], 1), team_sf=round(hist.team_shots_for(team), 1),
                    sog_pg=round(f["sog_pg"], 2), sog_l5=round(f["sog_l5"], 2), sog_l10=round(f["sog_l10"], 2),
                    hit2_l10=round(f["hit2_l10"], 2), hit3_l10=round(f["hit3_l10"], 2), goal_l10=round(f["goal_l10"], 2),
                    toi_l5=round(f["toi_l5"], 1),
                    sh_pct=round(f["sh_pct"], 3), pp_share=round(f["pp_share"], 2),
                    goals_l5=int(f["goals_l5"]), toi=round(f["toi_pg"], 1), n_games=f.get("n_games", 0),
                    p_goal=round(pg, 3), fair_goal=american(pg),
                    p_sog2=round(p_sog_at_least(f, 2, model), 3), p_sog3=round(p_sog_at_least(f, 3, model), 3),
                    p_sog4=round(p_sog_at_least(f, 4, model), 3),
                ))
    rows.sort(key=lambda r: -r["p_goal"])
    return rows, games, hist


def join_odds(rows, odds_path):
    """Attach book_goal / book_sogN (best American price) + book name to each row."""
    if not os.path.exists(odds_path):
        return None
    js = json.load(open(odds_path))
    players = js.get("players", {})
    hit = 0
    for r in rows:
        o = players.get(norm(r["full_name"])) or players.get(norm(r["name"]))
        r["book_goal"] = r["book_goal_bk"] = ""
        for k in ("sog2", "sog3", "sog4"):
            r[f"book_{k}"] = r[f"book_{k}_bk"] = ""
        if not o:
            continue
        hit += 1
        bk, px = best(o.get("goal", {}))
        if bk:
            r["book_goal"], r["book_goal_bk"] = px, bk
        # shots: books post ONE line per player (e.g. 2.5). Map it to the matching k.
        for bk, v in o.get("sog", {}).items():
            k = f"sog{int(v['line'] + 0.5)}"
            if k in ("sog2", "sog3", "sog4"):
                cur = r.get(f"book_{k}")
                if cur == "" or v["over"] > cur:
                    r[f"book_{k}"], r[f"book_{k}_bk"] = v["over"], bk
    print(f"[odds] matched {hit}/{len(rows)} board rows to book prices", file=sys.stderr)
    return js.get("meta", {})


def auto_picks(rows, d):
    """Rows where model beats the best book price by the market's bar. Returns picks list."""
    existing = {(r["date"], str(r["pid"]), r["market"]) for r in read_picks()}
    cands = []
    for r in rows:
        if r.get("status") in ("OUT", "?"):
            continue
        for m, _, pk in MARKETS:
            px = r.get(f"book_{m}")
            if px == "" or px is None:
                continue
            edge = r[pk] - implied(px)
            if edge >= EDGE_BAR[m] and (d.isoformat(), str(r["pid"]), m) not in existing:
                cands.append((edge, m, r, px))
    cands.sort(key=lambda t: -t[0])
    picked = []
    for edge, m, r, px in cands[:MAX_AUTO_PICKS]:
        line = {"goal": 0.5, "sog2": 1.5, "sog3": 2.5, "sog4": 3.5}[m]
        add_pick(d.isoformat(), r["pid"], r["name"], r["team"], r["opp"], m, line, int(px), 1.0,
                 r[{"goal": "p_goal", "sog2": "p_sog2", "sog3": "p_sog3", "sog4": "p_sog4"}[m]],
                 implied(px), note=f"auto {r.get(f'book_{m}_bk','')}")
        picked.append((r["name"], m, px, edge))
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--out", default=".", help="output dir ('docs' for GitHub Pages)")
    ap.add_argument("--goalie", action="append", default=[], help="TEAM=LastName override")
    ap.add_argument("--min-games", type=int, default=8)
    ap.add_argument("--auto-pick", action="store_true", help="append model picks to picks.csv")
    a = ap.parse_args()
    d = date.fromisoformat(a.date) if a.date else (datetime.now(timezone.utc) - timedelta(hours=4)).date()
    os.makedirs(os.path.join(a.out, "boards"), exist_ok=True)

    overrides = {}
    rows, games, hist = score_slate(d, {}, a.min_games)
    if a.goalie:
        for o in a.goalie:
            t, nm = o.split("=", 1)
            pid = next((p for p, n in hist.names.items() if nm.lower() in n.lower() and p in hist.gl), None)
            if pid:
                overrides[t.upper()] = pid
        if overrides:
            rows, games, hist = score_slate(d, overrides, a.min_games)

    odds_meta = join_odds(rows, os.path.join(a.out, "odds.json"))
    picked = auto_picks(rows, d) if (a.auto_pick and odds_meta) else []
    todays_picks = [r for r in read_picks() if r["date"] == d.isoformat()]

    with open(os.path.join(a.out, "board.csv"), "w", newline="") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    page = render(rows, games, d, odds_meta, todays_picks)
    open(os.path.join(a.out, "index.html"), "w").write(page)
    open(os.path.join(a.out, "boards", f"{d.isoformat()}.html"), "w").write(page)
    if not rows:
        print("no regular-season games on", d); return
    print(f"{'#':<3}{'player':<24}{'tm':<5}{'opp':<5}{'G':<3}{'SOG/g':>6}{'toi':>6}{'P(G)':>7}{'fair':>7}{'book':>7}{'P3+':>6}{'book3':>7}")
    for i, r in enumerate(rows[:25], 1):
        print(f"{i:<3}{r['name'][:23]:<24}{r['team']:<5}{r['opp']:<5}{r['pos']:<3}{r['sog_pg']:>6}{r['toi']:>6}"
              f"{r['p_goal']:>7}{r['fair_goal']:>7}{str(r.get('book_goal','')):>7}{r['p_sog3']:>6}{str(r.get('book_sog3','')):>7}")
    if picked:
        print("\nauto-picks:", "; ".join(f"{n} {m} @{px:+d} (+{e*100:.1f})" for n, m, px, e in picked))
    print(f"\n{len(rows)} players, {len(games)} games -> {a.out}/index.html")


from .page import render  # noqa: E402


if __name__ == "__main__":
    main()
