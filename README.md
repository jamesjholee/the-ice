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

## Backtest findings (2024-25 train → 2025-26 test, 83k player-games)
- Shots/game is the predictor. Top-5 by shots alone score 35–38% vs a 15% baseline. Nothing else comes close standalone.
- Position is the second thing: defensemen score ~7%. Once `is_d` is in the model, ice time flips to a strong positive (among forwards, minutes matter). The earlier "TOI is useless" read was a D confound.
- Opponent goalie: no measurable effect on anytime-goal rate. Among 3+ shot players, scoring is flat across goalie sv% buckets (32–35% everywhere). Weight −0.025. Do not pick players by goalie matchup.
- Hot streak (goals last 5): redundant with shots and finishing %. Weight +0.015.
- Finishing % (shrunk): real but small, +0.07. PP share (PP-goals proxy here; real PP TOI needs the stats API): small positive, unverified.
- Anytime-goal model is calibrated: top decile predicts 35%, actual 34%. That's roughly what books charge for second-tier scorers and well under what they charge for stars — a box-score model does not beat the ATG market on its own.
- Shot lines: raw Poisson is overconfident at the high end (says 75%, reality 64%). Platt calibration fixes it; every 2+/3+/4+ bucket now lands within a few points. Shot props are where the model's number is most trustworthy.
