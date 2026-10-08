# nhlprops — shot-volume scorer model, board, pick log, grader

Same rhythm as sixpts: build the board, log picks with the price you got, grade the next day, watch the record.

## Setup (once)
```
cd nhlprops
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
If you already have an `nhl_cache/` folder from the earlier backtest, copy it in here — the boxscores are reused.

## 1. Backtest + fit the model (once, then occasionally)
```
python -m nhl.backtest --seasons 2024 2025
```
Writes `model.json`. Adds what the first backtest was missing: real PP TOI (from the stats API — the boxscore endpoint has none), opponent starting goalie's rolling save%, a D flag, and calibration for 2+/3+/4+ shot lines. Prints the same bucket tables plus a goalie split and a PP split among 3+ shot players.

## 2. Daily
```
python -m nhl.board                          # today's slate -> board.html, board.csv
python -m nhl.board --goalie LAK=Kuemper     # once starters are confirmed, override the projection
open board.html                              # type book prices, see edge; tabs for goal / 2+ / 3+ / 4+ shots
python -m nhl.pick --date 2026-10-08 --player "Thompson" --market sog3 --odds -120
python -m nhl.pick --date 2026-10-08 --player "Reinhart" --market goal --odds +150 --stake 0.5
```

## 3. Next morning
```
python -m nhl.grade
```
Grades every ungraded pick from final boxscores, prints hit/miss per pick and the running record by market (hit rate, P&L, ROI, average model prob vs average book prob — if model > book over 100+ picks and ROI is positive, the edge is real; if model > book but ROI is negative, the model is overconfident).

## What the model is
`P(goal)` = logistic on standardized [shots/game, shrunk shooting %, PP TOI share, goals last 5, TOI, opp goalie sv%, is_D], all from the last 20 games before the game. `P(SOG ≥ k)` = Poisson on rolling shots/game × a calibration factor from the backtest.

## Known limits
- Projected opposing goalie = most frequent starter over the team's last 6 games. Override with `--goalie` once Daily Faceoff confirms.
- No linemate / line-slot data. Rookies and newly promoted wingers are underrated.
- Rosters come from `/roster/TEAM/current`; a scratched player still shows. Check the lineup.
- Odds are typed by hand; there's no feed. Closing-line value isn't tracked yet (column exists in the DB).
# the-ice
