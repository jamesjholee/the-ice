"""NHL public-API access with on-disk caching.

Endpoints (no key needed):
  api-web.nhle.com/v1/schedule/{date}              -> games on a date
  api-web.nhle.com/v1/gamecenter/{id}/boxscore     -> skater + goalie lines
  api-web.nhle.com/v1/roster/{TEAM}/current        -> today's roster
  api.nhle.com/stats/rest/en/skater/timeonice      -> per-game PP TOI (the boxscore
                                                      endpoint has no PP TOI field)
"""
import json, os, sys, time
from datetime import date, timedelta

import requests

WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"
CACHE = os.environ.get("NHL_CACHE", "nhl_cache")
os.makedirs(CACHE, exist_ok=True)

SEASON_WINDOWS = {
    2023: ("2023-10-10", "2024-04-18"),
    2024: ("2024-10-04", "2025-04-17"),
    2025: ("2025-10-07", "2026-04-16"),
    2026: ("2026-10-03", "2027-04-20"),
}


def season_id(season):           # 2025 -> "20252026"
    return f"{season}{season + 1}"


def season_of(d):
    return d.year if d.month >= 9 else d.year - 1


def _get(url, cache=True):
    key = os.path.join(CACHE, url.replace("https://", "").replace("/", "_").replace(":", "")[:200] + ".json")
    legacy = os.path.join(CACHE, url.replace("/", "_").replace(":", "") + ".json")  # first backtest's naming
    if cache:
        for k in (key, legacy):
            if os.path.exists(k):
                return json.load(open(k))
    last = None
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                js = r.json()
                if cache:
                    json.dump(js, open(key, "w"))
                return js
            last = r.status_code
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} -> {last}")


def toi_min(s):
    if not s:
        return 0.0
    try:
        m, sec = str(s).split(":")
        return int(m) + int(sec) / 60
    except ValueError:
        return 0.0


def games_on(d, final_only=True):
    """Return list of dicts {id, home, away, state} for regular-season games on date d."""
    # only cache schedules for past days (today's schedule changes state as games finish)
    sched = _get(f"{WEB}/schedule/{d.isoformat()}", cache=final_only and d < date.today())
    out = []
    for day in sched.get("gameWeek", []):
        if day["date"] != d.isoformat():
            continue
        for g in day["games"]:
            if g.get("gameType") != 2:
                continue
            st = g.get("gameState")
            if final_only and st not in ("OFF", "FINAL"):
                continue
            out.append(dict(id=g["id"], home=g["homeTeam"]["abbrev"], away=g["awayTeam"]["abbrev"],
                            state=st, start=g.get("startTimeUTC")))
    return out


def boxscore(game_id):
    """Return (skater_rows, goalie_rows). Each skater row:
       pid, name, team, opp, pos, goals, sog, toi, ppg, date
       goalie row: pid, name, team, opp, starter, saves, shots, date
    """
    b = _get(f"{WEB}/gamecenter/{game_id}/boxscore")
    gdate = b.get("gameDate")
    teams = {"homeTeam": b["homeTeam"]["abbrev"], "awayTeam": b["awayTeam"]["abbrev"]}
    skaters, goalies = [], []
    for side in ("awayTeam", "homeTeam"):
        team = teams[side]
        opp = teams["homeTeam" if side == "awayTeam" else "awayTeam"]
        pbg = b["playerByGameStats"][side]
        for grp in ("forwards", "defense"):
            for p in pbg.get(grp, []):
                skaters.append(dict(
                    pid=p["playerId"], name=p.get("name", {}).get("default", str(p["playerId"])),
                    team=team, opp=opp, pos="D" if grp == "defense" else "F",
                    goals=p.get("goals", 0), sog=p.get("sog", 0), toi=toi_min(p.get("toi")),
                    ppg=p.get("powerPlayGoals", 0), date=gdate, game_id=game_id,
                ))
        for g in pbg.get("goalies", []):
            saves, shots = 0, 0
            ssa = g.get("saveShotsAgainst")
            if isinstance(ssa, str) and "/" in ssa:
                a, c = ssa.split("/")
                saves, shots = int(a), int(c)
            goalies.append(dict(
                pid=g["playerId"], name=g.get("name", {}).get("default", str(g["playerId"])),
                team=team, opp=opp, starter=bool(g.get("starter", False)),
                saves=saves, shots=shots, toi=toi_min(g.get("toi")), date=gdate, game_id=game_id,
            ))
    return skaters, goalies


def pp_toi_by_game(season):
    """Return {(pid, game_id): pp_toi_minutes} for a season from the stats REST API.
    Pages through per-game rows. Returns {} with a warning if the endpoint shape differs."""
    key = os.path.join(CACHE, f"pptoi_{season}.json")
    if os.path.exists(key):
        return {tuple(map(int, k.split("|"))): v for k, v in json.load(open(key)).items()}
    out, start = {}, 0
    while True:
        url = (f"{STATS}/skater/timeonice?isAggregate=false&isGame=true&limit=100&start={start}"
               f"&sort=gameId&cayenneExp=seasonId={season_id(season)}%20and%20gameTypeId=2")
        try:
            js = _get(url, cache=False)
        except Exception as e:
            print(f"[pp_toi] fetch failed at start={start}: {e}", file=sys.stderr)
            break
        rows = js.get("data", [])
        if not rows:
            break
        for r in rows:
            pid, gid = r.get("playerId"), r.get("gameId")
            pp = r.get("ppTimeOnIce")
            if pid is None or gid is None or pp is None:
                continue
            out[(int(pid), int(gid))] = float(pp) / 60.0   # seconds -> minutes
        start += len(rows)
        if start % 5000 == 0:
            print(f"[pp_toi] {season}: {start} rows", file=sys.stderr)
        if len(rows) < 100:
            break
    if not out:
        print("[pp_toi] WARNING: no PP TOI rows parsed; pp_share will fall back to PP goals proxy.",
              file=sys.stderr)
    json.dump({f"{k[0]}|{k[1]}": v for k, v in out.items()}, open(key, "w"))
    return out


def roster(team):
    js = _get(f"{WEB}/roster/{team}/current", cache=False)
    out = []
    for grp in ("forwards", "defensemen"):
        for p in js.get(grp, []):
            nm = p.get("firstName", {}).get("default", "") + " " + p.get("lastName", {}).get("default", "")
            out.append(dict(pid=p["id"], name=nm.strip(), pos="D" if grp == "defensemen" else "F"))
    return out


def season_days(season):
    d, end = (date.fromisoformat(x) for x in SEASON_WINDOWS[season])
    while d <= end:
        yield d
        d += timedelta(days=1)
