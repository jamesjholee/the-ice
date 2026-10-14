"""Player-prop odds from The Odds API (api.the-odds-api.com).

Env: ODDS_API_KEY. Cost = markets × regions per event, only for markets with data.
We pull 2 markets × 1 region per game => ~2 credits/game, ~15/day on a normal slate.

Output: odds.json in the run dir — {pid_key: {"goal": {book: american, ...},
"sog": {book: {"line": 2.5, "over": american}}}} keyed by normalized player name,
plus a "meta" block with credits used/remaining.
"""
import json, os, re, sys, unicodedata
from datetime import datetime, timezone, timedelta

import requests

API = "https://api.the-odds-api.com/v4"
SPORT = "icehockey_nhl"
MARKETS = "player_goal_scorer_anytime,player_shots_on_goal"
PREFERRED_BOOKS = ["fanduel", "draftkings", "betmgm", "caesars", "fanatics", "espnbet", "betrivers"]


def norm(name):
    """'Connor McDavid' / 'C. McDavid' -> 'mcdavid|c'. Last name + first initial."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z\s\-']", "", s).strip()
    parts = s.split()
    if not parts:
        return s
    return f"{parts[-1]}|{parts[0][0]}"


def fetch(date_et, key, regions="us"):
    """Return (odds_by_player, meta). date_et: date object (ET)."""
    start = datetime(date_et.year, date_et.month, date_et.day, 4, 0, tzinfo=timezone.utc)  # 00:00 ET
    end = start + timedelta(days=1)
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(f"{API}/sports/{SPORT}/events",
                     params=dict(apiKey=key, commenceTimeFrom=fmt(start), commenceTimeTo=fmt(end)), timeout=30)
    r.raise_for_status()
    events = r.json()
    out, used, remaining = {}, 0, None
    for ev in events:
        rr = requests.get(f"{API}/sports/{SPORT}/events/{ev['id']}/odds",
                          params=dict(apiKey=key, regions=regions, markets=MARKETS, oddsFormat="american"),
                          timeout=30)
        remaining = rr.headers.get("x-requests-remaining", remaining)
        used += int(rr.headers.get("x-requests-last", 0) or 0)
        if rr.status_code != 200:
            print(f"[odds] {ev.get('away_team')} @ {ev.get('home_team')}: {rr.status_code}", file=sys.stderr)
            continue
        for bk in rr.json().get("bookmakers", []):
            book = bk["key"]
            for m in bk.get("markets", []):
                for o in m.get("outcomes", []):
                    who = norm(o.get("description", ""))
                    if not who:
                        continue
                    p = out.setdefault(who, {"goal": {}, "sog": {}, "name": o.get("description")})
                    if m["key"] == "player_goal_scorer_anytime" and o.get("name") == "Yes":
                        p["goal"][book] = int(o["price"])
                    elif m["key"] == "player_shots_on_goal" and o.get("name") == "Over":
                        p["sog"][book] = {"line": float(o.get("point", 0)), "over": int(o["price"])}
    meta = dict(fetched=datetime.now(timezone.utc).isoformat(), events=len(events),
                credits_used=used, credits_remaining=remaining)
    print(f"[odds] {len(events)} events, {len(out)} players, used {used} credits, {remaining} remaining", file=sys.stderr)
    return out, meta


def best(prices):
    """Best (highest) American price among preferred books. Returns (book, odds) or (None, None)."""
    cands = [(b, o) for b, o in prices.items()]
    if not cands:
        return None, None
    return max(cands, key=lambda t: t[1])


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("[odds] ODDS_API_KEY not set; skipping", file=sys.stderr); return
    from datetime import date
    d = date.fromisoformat(a.date) if a.date else (datetime.now(timezone.utc) - timedelta(hours=4)).date()
    odds, meta = fetch(d, key)
    json.dump({"meta": meta, "players": odds}, open(os.path.join(a.out, "odds.json"), "w"))


if __name__ == "__main__":
    main()
