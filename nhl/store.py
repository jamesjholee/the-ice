"""Pick log as a CSV in the repo (git-friendly; the Action grades it)."""
import csv, os

PICKS = os.environ.get("NHL_PICKS", "picks.csv")
FIELDS = ["id", "date", "pid", "name", "team", "opp", "market", "line", "odds", "stake",
          "model_p", "book_p", "close_odds", "result", "pnl", "note"]


def _read():
    if not os.path.exists(PICKS):
        return []
    with open(PICKS, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]
    # rows pasted from the board's "copy" button have no id; assign the next free one
    used = [int(r["id"]) for r in rows if (r.get("id") or "").strip()]
    nxt = 1 + max(used or [0])
    for r in rows:
        if not (r.get("id") or "").strip():
            r["id"] = str(nxt); nxt += 1
    return rows


def _write(rows):
    with open(PICKS, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def add_pick(date, pid, name, team, opp, market, line, odds, stake, model_p, book_p, note=""):
    rows = _read()
    nid = 1 + max([int(r["id"]) for r in rows if r.get("id")] or [0])
    rows.append(dict(id=nid, date=date, pid=pid, name=name, team=team, opp=opp, market=market,
                     line=line, odds=odds, stake=stake, model_p=f"{model_p:.4f}", book_p=f"{book_p:.4f}",
                     close_odds="", result="", pnl="", note=note))
    _write(rows)
    return nid


def ungraded(date=None):
    out = []
    for r in _read():
        if r.get("result", "") != "":
            continue
        if date and r["date"] != date:
            continue
        out.append((int(r["id"]), r["date"], int(r["pid"]), r["name"], r["team"], r["opp"], r["market"],
                    float(r["line"]), int(r["odds"]), float(r["stake"]), float(r["model_p"]), float(r["book_p"])))
    return out


def grade(pick_id, result, pnl, close_odds=None):
    rows = _read()
    for r in rows:
        if int(r["id"]) == pick_id:
            r["result"] = result
            r["pnl"] = f"{pnl:.4f}"
            if close_odds is not None:
                r["close_odds"] = close_odds
    _write(rows)


def record():
    """Return (per-market rows, total) matching the old SQLite shape."""
    g = [r for r in _read() if r.get("result", "") != ""]
    by = {}
    for r in g:
        m = by.setdefault(r["market"], [0, 0, 0.0, 0.0, 0.0, 0.0])
        m[0] += 1; m[1] += int(r["result"]); m[2] += float(r["pnl"]); m[3] += float(r["stake"])
        m[4] += float(r["model_p"]); m[5] += float(r["book_p"])
    rows = [(k, v[0], v[1], v[2], v[3], v[4] / v[0], v[5] / v[0]) for k, v in sorted(by.items())]
    tot = (len(g), sum(int(r["result"]) for r in g), sum(float(r["pnl"]) for r in g),
           sum(float(r["stake"]) for r in g)) if g else None
    return rows, tot


def graded_rows():
    return [r for r in _read() if r.get("result", "") != ""]
