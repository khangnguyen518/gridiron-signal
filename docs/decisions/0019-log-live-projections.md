# 0019. Log live projections for a forward test

- Status: Accepted
- Date: 2026-10-25
- Extends: 0011

## Context
Every result so far comes from backtests on 2019-2025, and those seasons have been used to pick
about ten modeling changes, so they are no longer a clean test. Two leaks were also found late:
Sleeper's stored projections were updated after inactives (0017), and backtests use closing lines
while live projections use midweek ones. The 2026 season is genuinely unseen, but nothing kept the
live numbers: the league tool writes CSVs to the VM's disk only.

## Decision
- `nflm log-projections` builds the league tool's full player table (`league.build_player_table`,
  the league's own scoring) and appends it to `nflm_raw.projection_snapshots`, one row per player
  per snapshot. It refreshes every cached table first.
- On the VM: daily at 15:00 UTC (before Thursday night and Sunday games), plus Sunday 16:45 UTC
  (after inactives for 1 p.m. ET games, before their kickoff, in both daylight and standard time).
  It shares the league job's lock so the two never run at once on the 1 GB VM.
- Each row keeps the shown projection, expected points (`center`), the 10th/50th/90th
  percentiles, ours, Sleeper's live projection, every adjustment (weight, shift, matchup,
  Questionable factors), injury and practice status, lines, kickoff time, the model card's SHA-256
  and the git commit, and the dbt target.
- `nflm_raw` stays append-only (0011). Rows from laptops are kept and marked by `dbt_target`.

## Evaluation, fixed before any data arrives
- Unit: for each player-game, the last snapshot with `snapshot_at` before that game's kickoff,
  from `dbt_target = 'prod'`, joined to league-scored actuals in `ff_marts`.
- Primary: MAE of `proj` against actual points for startable players (each week's top 12 QB,
  24 RB, 36 WR and 12 TE by Sleeper's live projection in the same snapshot), against Sleeper's live
  projection, with week-bootstrap 95% intervals (`significance.py`). Players who did not play count
  as 0, since the decision was made before knowing.
- Secondary: close-call accuracy (Sleeper within 2 points), lineup points lost against the best
  lineup in hindsight for a fixed set of rosters, and coverage of the 10-90 range.
- Read the scorecard at the end of the regular season. A mid-season look is fine for spotting
  bugs, not for changing the model on the result.
- Model changes during the season are allowed; each snapshot records its model card, so results
  can be split by model version.

## Why
- A forward test is the only clean test left, and every week not logged is lost.
- Logging what the tool showed, at the time it showed it, removes both known leaks by construction:
  midweek Sleeper, midweek lines, the injury report as it stood.
- Stating the metric now keeps the scorecard from being shaped by its results.

## Consequences
- About 3,200 rows per snapshot (every player Sleeper lists, free agents included), 8 snapshots a
  week: about 0.2 GB a season. The first row set (2026-10-25 01:30 UTC) came from a laptop (`dev`).
- One season of weekly data is about 18 weeks: enough to detect differences of a few tenths of a
  point in MAE, not the 0.005 effects some backtests found. Small changes stay backtest-only.
- `nflm league --refresh` now also refreshes the status and depth-chart caches, which it skipped
  before (stale practice status and depth charts on the VM).
