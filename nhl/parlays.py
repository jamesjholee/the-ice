"""Build the day's parlays from the scored board, price them, log them, post them.

Ticket shapes (revised Nov 4 after the first graded night — shots legs went 6/9, goal legs 2/9):
  core     3 x 3+ shots, three games, P >= .60, best edge first
  core2    3 x 3+ shots from three other games, P >= .55
  stack    3 x 2+ shots, one team's forwards, P >= .75 — same-game, positively correlated
  ladder4  4 x 4+ shots, four games, P >= .35
  shots6   6 x 2+ shots, six games, P >= .75 — the shots-only longshot
  goals4   4 x anytime goal, four games, 0.33-0.42 band, 3.0+ SOG/g forwards only — the one goal ticket
  No player appears on more than two tickets a night.

Pricing: fair = product of model probs (independent) → American. Book = product of the
best book price per leg when every leg has one; else blank. Edge = (book_implied vs fair).
Legs with status OUT or ? are never used. A leg is "ok" when its own market edge >= -2
(book can be slightly better than model on one leg of a stack).

Writes parlays.csv (one row per ticket, legs pipe-separated) that grade.py scores:
  a ticket hits only if every leg hits; void legs are removed and the ticket re-priced.
"""
import csv, json, os, sys
from collections import defaultdict
from itertools import combinations

from .features import american, implied

PARLAYS = os.environ.get("NHL_PARLAYS", "parlays.csv")
FIELDS = ["id", "date", "kind", "legs", "n_legs", "fair_p", "fair_odds", "book_odds", "book_p", "stake",
          "result", "pnl", "note"]
MK = {"goal": "p_goal", "sog2": "p_sog2", "sog3": "p_sog3", "sog4": "p_sog4"}
LINE = {"goal": 0.5, "sog2": 1.5, "sog3": 2.5, "sog4": 3.5}


def _eligible(rows):
    return [r for r in rows if r.get("status") not in ("OUT", "?")]


def _book(r, m):
    v = r.get(f"book_{m}")
    return int(v) if v not in ("", None) else None


def _mk_leg(r, m):
    return dict(pid=r["pid"], name=r["name"], team=r["team"], opp=r["opp"], game=r["game"], market=m,
                line=LINE[m], p=float(r[MK[m]]), book=_book(r, m))


def _price(legs):
    fair_p = 1.0
    for l in legs:
        fair_p *= l["p"]
    book_p = 1.0; have = True
    for l in legs:
        if l["book"] is None:
            have = False; break
        book_p *= implied(l["book"])
    dec = 1.0
    if have:
        for l in legs:
            o = l["book"]; dec *= (1 + o / 100) if o > 0 else (1 + 100 / -o)
    return fair_p, (round((dec - 1) * 100) if have else None), (book_p if have else None)


def _distinct_games(cands, k, key):
    out, seen = [], set()
    for r in cands:
        if r["game"] in seen:
            continue
        out.append(r); seen.add(r["game"])
        if len(out) == k:
            break
    return out


def _pace(rows):
    """Game -> pace score: both teams' shots-for plus both defenses' shots-allowed."""
    g = defaultdict(set)
    for r in rows:
        g[r["game"]].add((r["team"], float(r.get("team_sf", 28)), float(r.get("opp_sa", 28))))
    return {k: sum(sf + sa for _, sf, sa in s) for k, s in g.items()}


MAX_USES = 2   # no player anchors more than two tickets a night (Nov 3: Hagel sank four)


def build(rows):
    el = _eligible(rows)
    for r in el:
        for m in MK:
            r[MK[m]] = float(r[MK[m]])
    tickets = []
    used = defaultdict(int)

    def take(cands, k, market, distinct_games=True, min_p=0.0):
        """Pick up to k rows from cands (already sorted best-first), honoring the usage cap."""
        out, seen = [], set()
        for r in cands:
            if used[r["pid"]] >= MAX_USES or r[MK[market]] < min_p:
                continue
            if distinct_games and r["game"] in seen:
                continue
            out.append(r); seen.add(r["game"])
            if len(out) == k:
                break
        return out

    def commit(kind, pairs):
        legs = [_mk_leg(r, m) for r, m in pairs]
        for r, _ in pairs:
            used[r["pid"]] += 1
        tickets.append((kind, legs))

    def edge_key(m):
        def k(r):
            b = _book(r, m)
            return -(r[MK[m]] - implied(b)) if b else -(r[MK[m]] - 0.05)
        return k

    # ---- shots tickets (the model's strength) ----
    # core: 3 x 3+ shots, three games, P >= .60
    c = take(sorted(el, key=edge_key("sog3")), 3, "sog3", min_p=0.60)
    if len(c) == 3:
        commit("core", [(r, "sog3") for r in c])

    # stack: one team, three forwards 2+ shots >= .75
    by_team = defaultdict(list)
    for r in el:
        if r["p_sog2"] >= 0.75 and r["pos"] == "F" and used[r["pid"]] < MAX_USES:
            by_team[r["team"]].append(r)
    best = None
    for t, rs in by_team.items():
        if len(rs) >= 3:
            rs = sorted(rs, key=lambda r: -r["p_sog2"])[:3]
            score = rs[0]["p_sog2"] * rs[1]["p_sog2"] * rs[2]["p_sog2"]
            if best is None or score > best[0]:
                best = (score, rs)
    if best:
        commit("stack", [(r, "sog2") for r in best[1]])

    # ladder4: 4 x 4+ shots, four games, P >= .35
    l4 = take(sorted(el, key=lambda r: -r["p_sog4"]), 4, "sog4", min_p=0.35)
    if len(l4) == 4:
        commit("ladder4", [(r, "sog4") for r in l4])

    # shots6: 6 x 2+ shots, six games, P >= .78 — the shots-only longshot
    s6 = take(sorted(el, key=lambda r: -r["p_sog2"]), 6, "sog2", min_p=0.75)
    if len(s6) == 6:
        commit("shots6", [(r, "sog2") for r in s6])

    # shots3x3: three 3+ shots at P >= .55 from three *different* games than core if possible
    core_games = {l["game"] for k, legs in tickets if k == "core" for l in legs}
    alt = [r for r in sorted(el, key=edge_key("sog3")) if r["game"] not in core_games]
    a3 = take(alt, 3, "sog3", min_p=0.55)
    if len(a3) == 3:
        commit("core2", [(r, "sog3") for r in a3])

    # ---- the one goal ticket ----
    # goals4: anytime goal, 0.33-0.42 band, four games, best book edge first.
    # Only forwards with >= 3.0 SOG/g (Nov 3: the 0-SOG goal legs were all sub-3 shooters that night).
    band = sorted([r for r in el if 0.33 <= r["p_goal"] <= 0.42 and r["pos"] == "F" and float(r.get("sog_pg", 0)) >= 3.0],
                  key=edge_key("goal"))
    g4 = take(band, 4, "goal")
    if len(g4) == 4:
        commit("goals4", [(r, "goal") for r in g4])

    out = []
    for kind, legs in tickets:
        fair_p, book_odds, book_p = _price(legs)
        out.append(dict(kind=kind, legs=legs, fair_p=fair_p, fair_odds=american(fair_p), book_odds=book_odds, book_p=book_p))
    return out


def why(leg, rows_by_pid):
    r = rows_by_pid.get(leg["pid"], {})
    if not r:
        return ""
    g = "A" if float(r.get("opp_sa", 28)) >= 29 else "B" if float(r.get("opp_sa", 28)) >= 27 else "C"
    bits = [f"{r.get('sog_pg')} SOG/g", f"L5 {r.get('sog_l5')}", f"{r.get('toi')} min"]
    if float(r.get("pp_share", 0)) >= 0.18:
        bits.append(f"PP {float(r['pp_share']):.0%}")
    bits.append(f"vs {leg['opp']} {g} ({r.get('opp_sa')})")
    if leg["market"] == "goal":
        bits.append(f"sh% {float(r.get('sh_pct', 0)) * 100:.1f}")
    return " · ".join(bits)


def _read():
    if not os.path.exists(PARLAYS):
        return []
    with open(PARLAYS, newline="") as fh:
        return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def _write(rows):
    with open(PARLAYS, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def log(tickets, date):
    rows = _read()
    existing = {(r["date"], r["kind"]) for r in rows}
    nid = 1 + max([int(r["id"]) for r in rows if r.get("id")] or [0])
    added = []
    for t in tickets:
        if (date, t["kind"]) in existing:
            continue
        legs = "|".join(f"{l['pid']}:{l['name']}:{l['market']}:{l['line']}:{l['book'] if l['book'] is not None else ''}:{l['p']:.3f}" for l in t["legs"])
        rows.append(dict(id=nid, date=date, kind=t["kind"], legs=legs, n_legs=len(t["legs"]), fair_p=f"{t['fair_p']:.5f}",
                         fair_odds=t["fair_odds"], book_odds=t["book_odds"] if t["book_odds"] is not None else "",
                         book_p=f"{t['book_p']:.5f}" if t["book_p"] else "", stake=1.0, result="", pnl="", note=""))
        added.append(t); nid += 1
    _write(rows)
    return added


def grade_parlays(stats_by_date):
    """stats_by_date: date -> {pid: skater boxscore row}. Grades every ungraded ticket whose games are final."""
    rows = _read(); changed = 0
    for r in rows:
        if r.get("result", "") != "":
            continue
        stats = stats_by_date.get(r["date"])
        if not stats:
            continue
        legs = [l.split(":") for l in r["legs"].split("|")]
        hit_all = True; live = []; dec = 1.0; any_missing = False
        for pid, name, m, line, book, p in legs:
            s = stats.get(int(pid))
            if s is None:
                any_missing = True; continue            # void leg (scratch)
            val = s["goals"] if m == "goal" else s["sog"]
            ok = val > float(line)
            hit_all &= ok; live.append(ok)
            if book:
                o = int(book); dec *= (1 + o / 100) if o > 0 else (1 + 100 / -o)
        if not live:
            r["result"] = "0"; r["pnl"] = "0"; r["note"] = "all legs void"; changed += 1; continue
        if any_missing and not r.get("book_odds"):
            pass
        res = 1 if hit_all else 0
        stake = float(r.get("stake") or 1)
        payout = (dec - 1) * stake if r.get("book_odds") else (1 / float(r["fair_p"]) - 1) * stake
        r["result"] = str(res); r["pnl"] = f"{payout if res else -stake:.4f}"
        if any_missing:
            r["note"] = (r.get("note") or "") + " void leg(s) removed"
        changed += 1
    if changed:
        _write(rows)
    return changed


def record():
    g = [r for r in _read() if r.get("result", "") != ""]
    if not g:
        return None
    by = defaultdict(lambda: [0, 0, 0.0])
    for r in g:
        b = by[r["kind"]]; b[0] += 1; b[1] += int(r["result"]); b[2] += float(r["pnl"])
    tot = [len(g), sum(int(r["result"]) for r in g), sum(float(r["pnl"]) for r in g)]
    return dict(by=dict(by), total=tot)


def discord(tickets, rows_by_pid, date, url):
    import requests
    lines = [f"**the-ice · {date} · model parlays**"]
    for t in tickets:
        hdr = f"\n**{t['kind']}** · {len(t['legs'])} legs · fair {t['fair_odds']}"
        if t["book_odds"] is not None:
            edge = t["fair_p"] / t["book_p"]
            hdr += f" · book **{t['book_odds']:+d}** ({'%.1fx' % edge} vs fair)"
        lines.append(hdr)
        for l in t["legs"]:
            mk = {"goal": "ATG", "sog2": "2+ SOG", "sog3": "3+ SOG", "sog4": "4+ SOG"}[l["market"]]
            px = f" @ {l['book']:+d}" if l["book"] is not None else ""
            lines.append(f"• {l['name']} ({l['team']}) {mk}{px} — {l['p']:.0%} · {why(l, rows_by_pid)}")
    body = "\n".join(lines)
    for chunk in [body[i:i + 1900] for i in range(0, len(body), 1900)]:
        requests.post(url, json={"content": chunk}, timeout=20)


def main():
    import argparse
    from datetime import date, datetime, timezone, timedelta
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--board", default="docs/board.csv")
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--post", action="store_true")
    a = ap.parse_args()
    d = a.date or (datetime.now(timezone.utc) - timedelta(hours=5)).date().isoformat()
    rows = list(csv.DictReader(open(a.board)))
    for r in rows:
        r["pid"] = int(r["pid"])
    by_pid = {r["pid"]: r for r in rows}
    tickets = build(rows)
    for t in tickets:
        print(f"\n[{t['kind']}] fair {t['fair_odds']} ({t['fair_p']:.3%})" + (f"  book {t['book_odds']:+d}  ({t['fair_p']/t['book_p']:.2f}x fair)" if t["book_odds"] is not None else "  (no book prices)"))
        for l in t["legs"]:
            print(f"   {l['name']:<16}{l['team']:<4}{l['market']:<5}{l['p']:.0%}  {('@%+d' % l['book']) if l['book'] is not None else '':<6} {why(l, by_pid)}")
    if a.log:
        added = log(tickets, d); print(f"\nlogged {len(added)} tickets to {PARLAYS}")
    url = os.environ.get("DISCORD_WEBHOOK")
    if a.post and url and tickets:
        discord(tickets, by_pid, d, url); print("posted to Discord")
    out_dir = os.path.dirname(a.board) or "."
    json.dump([dict(t, legs=t["legs"]) for t in tickets], open(os.path.join(out_dir, "parlays.json"), "w"))
    # re-render the page so the Parlays panel reflects today's tickets (board.py ran before us)
    try:
        from .page import render
        from .store import _read as read_picks
        from datetime import date as _date
        games = []
        seen = set()
        for r in rows:
            if r["game"] not in seen:
                seen.add(r["game"]); aw, hm = r["game"].split("@"); games.append(dict(away=aw, home=hm, start=r.get("start", "")))
        for r in rows:
            for k in ("sog_pg", "sog_l5", "sog_l10", "hit2_l10", "hit3_l10", "goal_l10", "toi", "toi_l5", "pp_share", "sh_pct", "opp_sa", "team_sf", "p_goal", "p_sog2", "p_sog3", "p_sog4", "opp_gsv", "goals_l5"):
                if r.get(k) not in ("", None):
                    r[k] = float(r[k])
            for m in ("goal", "sog2", "sog3", "sog4"):
                v = r.get(f"book_{m}")
                r[f"book_{m}"] = int(v) if v not in ("", None) else ""
        meta = None
        mp = os.path.join(out_dir, "odds_meta.json")
        if os.path.exists(mp):
            meta = json.load(open(mp))
        picks = [x for x in read_picks() if x["date"] == d]
        page = render(rows, games, _date.fromisoformat(d), meta, picks, out_dir=out_dir)
        open(os.path.join(out_dir, "index.html"), "w").write(page)
        open(os.path.join(out_dir, "boards", f"{d}.html"), "w").write(page)
        print("page re-rendered with parlays")
    except Exception as e:
        print("[parlays] re-render skipped:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
