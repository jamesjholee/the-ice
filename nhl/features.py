"""Rolling pre-game features and the probability model.

Everything here is computed from games strictly BEFORE the game being predicted.
"""
import json, math, os
from collections import defaultdict

FEATS = ["sog_pg", "sh_pct", "pp_share", "goals_l5", "toi_pg", "opp_gsv", "is_d"]
DEFAULT_MODEL = {  # fallback weights if model.json hasn't been fitted yet (standardized inputs)
    "bias": -1.82, "w": {"sog_pg": 0.40, "sh_pct": 0.18, "pp_share": 0.05, "goals_l5": 0.0,
                          "toi_pg": -0.08, "opp_gsv": -0.05, "is_d": -0.10},
    "mu": {"sog_pg": 1.7, "sh_pct": 0.10, "pp_share": 0.08, "goals_l5": 0.8, "toi_pg": 16.7,
           "opp_gsv": 0.905, "is_d": 0.33},
    "sd": {"sog_pg": 1.0, "sh_pct": 0.02, "pp_share": 0.09, "goals_l5": 1.0, "toi_pg": 3.5,
           "opp_gsv": 0.012, "is_d": 0.47},
}
LEAGUE_SV = 0.905


class History:
    """Holds per-player and per-goalie game logs; call add_game() in date order."""

    def __init__(self, lookback=20):
        self.lookback = lookback
        self.sk = defaultdict(list)        # pid -> skater rows
        self.gl = defaultdict(list)        # goalie pid -> goalie rows
        self.team_goalies = defaultdict(list)   # team -> [(date, goalie pid)] starters
        self.pos = {}
        self.names = {}
        self.pptoi = {}                    # (pid, game_id) -> minutes

    def add_pptoi(self, mapping):
        self.pptoi.update(mapping)

    def add_game(self, skaters, goalies):
        for r in skaters:
            r = dict(r)
            r["pptoi"] = self.pptoi.get((r["pid"], r["game_id"]), None)
            self.sk[r["pid"]].append(r)
            self.pos[r["pid"]] = r["pos"]
            self.names[r["pid"]] = r["name"]
        for g in goalies:
            self.gl[g["pid"]].append(g)
            self.names[g["pid"]] = g["name"]
            if g["starter"]:
                self.team_goalies[g["team"]].append((g["date"], g["pid"]))

    # ---- goalie ----
    def goalie_sv(self, gpid, n=25):
        h = self.gl[gpid][-n:]
        saves = sum(x["saves"] for x in h)
        shots = sum(x["shots"] for x in h)
        # shrink toward league average with a 300-shot prior
        return (saves + LEAGUE_SV * 300) / (shots + 300)

    def likely_starter(self, team):
        """Most frequent starter over the team's last 6 games (pre-game guess)."""
        h = self.team_goalies[team][-6:]
        if not h:
            return None
        cnt = defaultdict(int)
        for _, g in h:
            cnt[g] += 1
        return max(cnt, key=cnt.get)

    # ---- skater ----
    def skater_feats(self, pid, opp_goalie_pid=None, min_games=8):
        h = self.sk[pid][-self.lookback:]
        if len(h) < min_games:
            return None
        n = len(h)
        sog = sum(x["sog"] for x in h) / n
        toi = sum(x["toi"] for x in h) / n
        shots = sum(x["sog"] for x in h)
        goals = sum(x["goals"] for x in h)
        sh = (goals + 10) / (shots + 100)
        g5 = sum(x["goals"] for x in h[-5:])
        pp_rows = [x for x in h if x["pptoi"] is not None]
        if pp_rows:
            pp = sum(x["pptoi"] for x in pp_rows) / max(1e-9, sum(x["toi"] for x in pp_rows))
        else:  # proxy: PP goals per game scaled to a share-like range
            pp = min(0.35, 0.4 * sum(x["ppg"] for x in h) / n)
        opp = self.goalie_sv(opp_goalie_pid) if opp_goalie_pid else LEAGUE_SV
        return dict(sog_pg=sog, sh_pct=sh, pp_share=pp, goals_l5=g5, toi_pg=toi,
                    opp_gsv=opp, is_d=1.0 if self.pos.get(pid) == "D" else 0.0)


# ---- probability model ----
def load_model(path="model.json"):
    if os.path.exists(path):
        return json.load(open(path))
    return DEFAULT_MODEL


def p_goal(f, model):
    z = model["bias"]
    for k in FEATS:
        z += model["w"][k] * (f[k] - model["mu"][k]) / model["sd"][k]
    return 1 / (1 + math.exp(-z))


def p_sog_at_least(f, k, model=None):
    """P(SOG >= k) from a Poisson on the player's rolling shot rate, lightly adjusted for
    opponent goalie (worse goalie -> more rebounds/shots is small; we ignore) and D flag."""
    lam = f["sog_pg"]
    p = 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))
    # Platt-style calibration fitted in backtest: logit(actual) = a + b*logit(poisson)
    cal = (model or {}).get("sog_platt", {}).get(str(k))
    if cal:
        p = min(max(p, 1e-4), 1 - 1e-4)
        z = cal[0] + cal[1] * math.log(p / (1 - p))
        p = 1 / (1 + math.exp(-z))
    return p


def american(p):
    p = min(max(p, 0.01), 0.99)
    return f"+{round(100 * (1 - p) / p)}" if p < 0.5 else f"-{round(100 * p / (1 - p))}"


def implied(odds):
    o = int(str(odds).replace("+", ""))
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def payout(odds, stake=1.0):
    o = int(str(odds).replace("+", ""))
    return stake * (o / 100 if o > 0 else 100 / -o)
