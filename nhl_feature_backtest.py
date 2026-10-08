#!/usr/bin/env python3
"""
Which numbers actually predict an NHL anytime goal?

Walks the regular season day by day. For each skater on each slate, computes
several candidate predictors using ONLY games before that day, ranks the slate
by each predictor separately, and measures the top-10 / top-20 hit rate
(scored >= 1 goal) against the league baseline. Also fits a tiny logistic
regression on all features (train season 1 -> test season 2) so you can see
the combined edge out-of-sample.

Predictors tested (all rolling over the last LOOKBACK games):
  sog_pg        shots on goal per game                   <- our core thesis
  toi_pg        time on ice per game
  pp_share      PP TOI / total TOI                       <- "is he on PP1"
  goals_l5      goals in last 5 games                    <- "hot streak" (control)
  sh_pct        shooting % (shrunk toward 10%)
  ixg_proxy     sog_pg * sh_pct_shrunk                   <- poor man's xG
  combo         sog_pg*(0.09+0.6*sh)*(1+0.5*pp)*(toi/18)  <- what we used Oct 6

Usage:
  pip install requests numpy
  python nhl_feature_backtest.py --seasons 2024 2025
     (2024 = 2024-25 season, 2025 = 2025-26). First run ~30-45 min, cached after.
"""
import argparse, json, math, os, sys, time
from collections import defaultdict
from datetime import date, timedelta

import requests
try:
    import numpy as np
except ImportError:
    np = None

API = "https://api-web.nhle.com/v1"
CACHE = "nhl_cache"
os.makedirs(CACHE, exist_ok=True)
SEASON_WINDOWS = {  # approx regular-season date ranges
    2023: ("2023-10-10", "2024-04-18"),
    2024: ("2024-10-04", "2025-04-17"),
    2025: ("2025-10-07", "2026-04-16"),
}


def get(url):
    key = os.path.join(CACHE, url.replace("/", "_").replace(":", "") + ".json")
    if os.path.exists(key):
        return json.load(open(key))
    for attempt in range(5):
        r = requests.get(url, timeout=25)
        if r.status_code == 200:
            json.dump(r.json(), open(key, "w"))
            return r.json()
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} -> {r.status_code}")


def toi_min(s):
    if not s:
        return 0.0
    m, sec = s.split(":")
    return int(m) + int(sec) / 60


def games_on(d):
    sched = get(f"{API}/schedule/{d.isoformat()}")
    ids = []
    for day in sched.get("gameWeek", []):
        if day["date"] != d.isoformat():
            continue
        for g in day["games"]:
            if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL"):
                ids.append(g["id"])
    return ids


def box(gid):
    b = get(f"{API}/gamecenter/{gid}/boxscore")
    rows = []
    for side in ("awayTeam", "homeTeam"):
        for grp in ("forwards", "defense"):
            for p in b["playerByGameStats"][side][grp]:
                rows.append(dict(
                    pid=p["playerId"], pos=grp,
                    goals=p.get("goals", 0), sog=p.get("sog", 0),
                    toi=toi_min(p.get("toi")), pptoi=toi_min(p.get("powerPlayToi")),
                ))
    return rows


def features(hist, lookback):
    h = hist[-lookback:]
    if len(h) < 8:
        return None
    n = len(h)
    sog = sum(x["sog"] for x in h) / n
    toi = sum(x["toi"] for x in h) / n
    pp = sum(x["pptoi"] for x in h) / max(1e-9, sum(x["toi"] for x in h))
    shots = sum(x["sog"] for x in h); goals = sum(x["goals"] for x in h)
    sh = (goals + 10) / (shots + 100)
    g5 = sum(x["goals"] for x in h[-5:])
    return dict(
        sog_pg=sog, toi_pg=toi, pp_share=pp, goals_l5=g5, sh_pct=sh,
        ixg_proxy=sog * sh,
        combo=sog * (0.09 + 0.6 * sh) * (1 + 0.5 * pp) * (toi / 18),
    )


FEATS = ["sog_pg", "toi_pg", "pp_share", "goals_l5", "sh_pct", "ixg_proxy", "combo"]


def run_season(season, lookback, warmup_days):
    d, end = (date.fromisoformat(x) for x in SEASON_WINDOWS[season])
    hist = defaultdict(list)
    samples = []            # (feature dict, hit, date)
    day_idx = 0
    while d <= end:
        try:
            gids = games_on(d)
        except Exception as e:
            print("skip", d, e, file=sys.stderr); d += timedelta(days=1); continue
        if gids:
            rows = []
            for gid in gids:
                try: rows.extend(box(gid))
                except Exception as e: print("skip game", gid, e, file=sys.stderr)
            if day_idx >= warmup_days:
                slate = []
                for r in rows:
                    f = features(hist[r["pid"]], lookback)
                    if f: slate.append((f, 1 if r["goals"] >= 1 else 0))
                # per-feature rank buckets within this slate
                for feat in FEATS:
                    ranked = sorted(slate, key=lambda t: -t[0][feat])
                    for i, (f, hit) in enumerate(ranked, 1):
                        f.setdefault("_rank", {})[feat] = i
                samples.extend((f, hit, d.isoformat()) for f, hit in slate)
            for r in rows:
                hist[r["pid"]].append(r)
            day_idx += 1
            print(season, d, f"{len(gids)} games", file=sys.stderr)
        d += timedelta(days=1)
    return samples


def bucket_report(samples, label):
    base = sum(h for _, h, _ in samples) / max(1, len(samples))
    print(f"\n=== {label}: {len(samples)} player-games, baseline anytime rate {base:.3f} ===")
    print(f"{'predictor':<11}{'top5':>8}{'top10':>8}{'top20':>8}{'21-40':>8}{'rest':>8}   (hit rate when ranking slate by this number alone)")
    for feat in FEATS:
        b = defaultdict(lambda: [0, 0])
        for f, hit, _ in samples:
            r = f["_rank"][feat]
            k = "top5" if r <= 5 else "top10" if r <= 10 else "top20" if r <= 20 else "21-40" if r <= 40 else "rest"
            b[k][0] += hit; b[k][1] += 1
        cells = []
        for k in ("top5", "top10", "top20", "21-40", "rest"):
            h, n = b[k]; cells.append(f"{h/n:>8.3f}" if n else f"{'-':>8}")
        print(f"{feat:<11}" + "".join(cells))
    print("Read: a predictor is useful if its top5/top10 columns are well above baseline AND above the other rows.")
    print("Typical anytime prices: -150 = 60%, +100 = 50%, +150 = 40%, +200 = 33%.")


def logistic(train, test):
    if np is None:
        print("\n(numpy not installed; skipping combined logistic model)"); return
    def X(s): return np.array([[f[k] for k in FEATS if k != "combo"] for f, _, _ in s])
    def y(s): return np.array([h for _, h, _ in s], dtype=float)
    Xtr, ytr, Xte, yte = X(train), y(train), X(test), y(test)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    Xtr = np.c_[np.ones(len(Xtr)), (Xtr - mu) / sd]; Xte = np.c_[np.ones(len(Xte)), (Xte - mu) / sd]
    w = np.zeros(Xtr.shape[1])
    for _ in range(300):  # plain gradient descent, L2
        p = 1 / (1 + np.exp(-Xtr @ w))
        w -= 0.5 * (Xtr.T @ (p - ytr) / len(ytr) + 1e-3 * w)
    p = 1 / (1 + np.exp(-Xte @ w))
    names = ["bias"] + [k for k in FEATS if k != "combo"]
    print("\n=== Combined logistic model (trained on season 1, tested on season 2) ===")
    print("standardized weights:", {n: round(float(v), 3) for n, v in zip(names, w)})
    order = np.argsort(-p)
    for k in (5, 10, 20, 40):
        top = order[: int(len(order) * k / 100)] if False else None
    # calibration by predicted-prob decile
    dec = np.quantile(p, np.linspace(0, 1, 11))
    print(f"{'pred bucket':<14}{'n':>7}{'actual':>9}{'predicted':>11}")
    for i in range(10):
        m = (p >= dec[i]) & (p <= dec[i + 1])
        if m.sum():
            print(f"{dec[i]:.2f}-{dec[i+1]:.2f}    {m.sum():>7}{yte[m].mean():>9.3f}{p[m].mean():>11.3f}")
    print("If 'actual' tracks 'predicted' down the column, the model is calibrated and the top bucket's rate is your edge vs the book.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=14)
    a = ap.parse_args()
    all_s = {}
    for s in a.seasons:
        all_s[s] = run_season(s, a.lookback, a.warmup)
        bucket_report(all_s[s], f"{s}-{str(s+1)[2:]} season")
    if len(a.seasons) >= 2:
        logistic(all_s[a.seasons[0]], all_s[a.seasons[-1]])
    with open("feature_samples.csv", "w") as f:
        f.write("season,date,hit," + ",".join(FEATS) + "\n")
        for s, samples in all_s.items():
            for feat, hit, d in samples:
                f.write(f"{s},{d},{hit}," + ",".join(f"{feat[k]:.4f}" for k in FEATS) + "\n")
    print("\nraw rows written to feature_samples.csv")


if __name__ == "__main__":
    main()
