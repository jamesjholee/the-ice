"""Build a History object up to (but not including) a date, from cached boxscores."""
import sys
from datetime import date, timedelta

from .data import games_on, boxscore, pp_toi_by_game, season_of, SEASON_WINDOWS
from .features import History


def build_history(upto, lookback=20, prior_days=200):
    """Ingest every final game from (upto - prior_days) through (upto - 1 day)."""
    hist = History(lookback=lookback)
    start = upto - timedelta(days=prior_days)
    seasons = {season_of(start), season_of(upto)}
    for s in seasons:
        if s in SEASON_WINDOWS:
            try:
                hist.add_pptoi(pp_toi_by_game(s))
            except Exception as e:
                print("[history] pp toi unavailable for", s, e, file=sys.stderr)
    d = start
    while d < upto:
        s = season_of(d)
        if s in SEASON_WINDOWS:
            lo, hi = (date.fromisoformat(x) for x in SEASON_WINDOWS[s])
            if lo <= d <= hi:
                try:
                    for g in games_on(d):
                        sk, gl = boxscore(g["id"])
                        hist.add_game(sk, gl)
                except Exception as e:
                    print("[history] skip", d, e, file=sys.stderr)
        d += timedelta(days=1)
    return hist
