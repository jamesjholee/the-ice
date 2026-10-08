"""Walk-forward backtest. Fits model.json used by board.py.

python -m nhl.backtest --seasons 2024 2025
"""
import argparse, json, sys
from collections import defaultdict

import numpy as np

from .data import games_on, boxscore, pp_toi_by_game, season_days
from .features import History, FEATS, p_sog_at_least, american


def collect(season, hist, warmup=14):
    hist.add_pptoi(pp_toi_by_game(season))
    samples, day_idx = [], 0
    for d in season_days(season):
        try:
            games = games_on(d)
        except Exception as e:
            print("skip", d, e, file=sys.stderr); continue
        if not games:
            continue
        todays = []
        for g in games:
            try:
                todays.append(boxscore(g["id"]))
            except Exception as e:
                print("skip game", g["id"], e, file=sys.stderr)
        if day_idx >= warmup:
            for skaters, goalies in todays:
                starters = {g["team"]: g["pid"] for g in goalies if g["starter"]}
                slate = []
                for r in skaters:
                    f = hist.skater_feats(r["pid"], opp_goalie_pid=starters.get(r["opp"]))
                    if f:
                        slate.append(dict(f=f, hit=1 if r["goals"] >= 1 else 0, sog=r["sog"],
                                          date=d.isoformat(), name=r["name"]))
                samples.extend(slate)
            # rank within the whole day's slate for the bucket report
            day_slate = [s for s in samples if s["date"] == d.isoformat()]
            for feat in FEATS:
                for i, s in enumerate(sorted(day_slate, key=lambda s: -s["f"][feat]), 1):
                    s.setdefault("rank", {})[feat] = i
        for skaters, goalies in todays:
            hist.add_game(skaters, goalies)
        day_idx += 1
        print(season, d, f"{len(games)} games", file=sys.stderr)
    return samples


def bucket_report(samples, label):
    base = np.mean([s["hit"] for s in samples])
    print(f"\n=== {label}: {len(samples)} player-games, baseline {base:.3f} ===")
    print(f"{'predictor':<10}{'top5':>8}{'top10':>8}{'top20':>8}{'21-40':>8}{'rest':>8}")
    for feat in FEATS:
        b = defaultdict(lambda: [0, 0])
        for s in samples:
            r = s["rank"][feat]
            k = "top5" if r <= 5 else "top10" if r <= 10 else "top20" if r <= 20 else "21-40" if r <= 40 else "rest"
            b[k][0] += s["hit"]; b[k][1] += 1
        print(f"{feat:<10}" + "".join(f"{b[k][0]/b[k][1]:>8.3f}" if b[k][1] else f"{'-':>8}"
                                      for k in ("top5", "top10", "top20", "21-40", "rest")))
    # opp goalie split among 3+ shot players
    strong = [s for s in samples if s["f"]["sog_pg"] >= 3]
    print("\n3+ shots/game players by opponent goalie rolling sv%:")
    for lo, hi in ((0, 0.895), (0.895, 0.905), (0.905, 0.915), (0.915, 1)):
        g = [s["hit"] for s in strong if lo <= s["f"]["opp_gsv"] < hi]
        if g:
            print(f"  gsv {lo:.3f}-{hi:.3f} n={len(g):>5} scored {np.mean(g):.3f}  fair {american(np.mean(g))}")
    print("3+ shots/game players by pp_share:")
    for lo, hi in ((0, 0.05), (0.05, 0.12), (0.12, 0.2), (0.2, 1)):
        g = [s["hit"] for s in strong if lo <= s["f"]["pp_share"] < hi]
        if g:
            print(f"  pp {lo:.2f}-{hi:.2f} n={len(g):>5} scored {np.mean(g):.3f}")


def sog_report(samples, label):
    print(f"\n=== SOG lines, {label}: Poisson on rolling shots/game ===")
    for k in (2, 3, 4):
        pred = np.array([p_sog_at_least(s["f"], k) for s in samples])
        act = np.array([1 if s["sog"] >= k else 0 for s in samples])
        print(f"SOG>={k}: predicted {pred.mean():.3f}  actual {act.mean():.3f}")
        for lo, hi in ((0, .3), (.3, .5), (.5, .7), (.7, 1.01)):
            m = (pred >= lo) & (pred < hi)
            if m.sum():
                print(f"   pred {lo:.1f}-{hi:.1f}: n={m.sum():>6} actual {act[m].mean():.3f} (pred {pred[m].mean():.3f})")


def fit(train, test):
    X = lambda S: np.array([[s["f"][k] for k in FEATS] for s in S])
    y = lambda S: np.array([s["hit"] for s in S], dtype=float)
    Xtr, ytr, Xte, yte = X(train), y(train), X(test), y(test)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    Z = lambda A: np.c_[np.ones(len(A)), (A - mu) / sd]
    Ztr, Zte = Z(Xtr), Z(Xte)
    w = np.zeros(Ztr.shape[1])
    for _ in range(400):
        p = 1 / (1 + np.exp(-Ztr @ w))
        w -= 0.5 * (Ztr.T @ (p - ytr) / len(ytr) + 1e-3 * w)
    p = 1 / (1 + np.exp(-Zte @ w))
    print("\n=== Logistic (train -> test) standardized weights ===")
    for n, v in zip(["bias"] + FEATS, w):
        print(f"  {n:<9}{v:+.3f}")
    dec = np.quantile(p, np.linspace(0, 1, 11))
    print(f"{'pred':<12}{'n':>7}{'actual':>9}{'predicted':>11}")
    for i in range(10):
        m = (p >= dec[i]) & (p <= dec[i + 1])
        if m.sum():
            print(f"{dec[i]:.2f}-{dec[i+1]:.2f}   {m.sum():>7}{yte[m].mean():>9.3f}{p[m].mean():>11.3f}")
    # SOG calibration: Platt scaling per line, fitted on TRAIN, reported on TEST
    platt = {}
    print("\n=== SOG line calibration (Platt, fitted on train, shown on test) ===")
    for k in (2, 3, 4):
        def logit(p): p = np.clip(p, 1e-4, 1 - 1e-4); return np.log(p / (1 - p))
        xtr = logit(np.array([p_sog_at_least(s["f"], k) for s in train]))
        ytr_k = np.array([1 if s["sog"] >= k else 0 for s in train], dtype=float)
        a, b = 0.0, 1.0
        for _ in range(500):
            p = 1 / (1 + np.exp(-(a + b * xtr)))
            ga, gb = np.mean(p - ytr_k), np.mean((p - ytr_k) * xtr)
            a -= 0.5 * ga; b -= 0.5 * gb
        platt[str(k)] = [float(a), float(b)]
        cal_model = {"sog_platt": platt}
        pte = np.array([p_sog_at_least(s["f"], k, cal_model) for s in test])
        yte_k = np.array([1 if s["sog"] >= k else 0 for s in test])
        print(f"SOG>={k}: a={a:+.3f} b={b:.3f}")
        for lo, hi in ((0, .3), (.3, .5), (.5, .7), (.7, 1.01)):
            m = (pte >= lo) & (pte < hi)
            if m.sum():
                print(f"   pred {lo:.1f}-{hi:.1f}: n={m.sum():>6} actual {yte_k[m].mean():.3f} (pred {pte[m].mean():.3f})")
    model = dict(bias=float(w[0]), w={k: float(v) for k, v in zip(FEATS, w[1:])},
                 mu={k: float(v) for k, v in zip(FEATS, mu)}, sd={k: float(v) for k, v in zip(FEATS, sd)},
                 sog_platt=platt)
    json.dump(model, open("model.json", "w"), indent=1)
    print("\nmodel.json written (used by board.py)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int, default=[2024, 2025])
    ap.add_argument("--lookback", type=int, default=20)
    a = ap.parse_args()
    hist = History(lookback=a.lookback)     # history carries across seasons
    per = {}
    for s in a.seasons:
        per[s] = collect(s, hist)
        bucket_report(per[s], f"{s}-{str(s+1)[2:]}")
        sog_report(per[s], f"{s}-{str(s+1)[2:]}")
    if len(a.seasons) >= 2:
        train = [x for s in a.seasons[:-1] for x in per[s]]
        fit(train, per[a.seasons[-1]])
    else:
        fit(per[a.seasons[0]], per[a.seasons[0]])


if __name__ == "__main__":
    main()
