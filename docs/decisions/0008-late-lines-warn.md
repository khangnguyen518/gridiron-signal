# 0008. Late-stored lines warn instead of failing

- Status: Accepted
- Date: 2026-10-21

## Context
When sports_db's loader missed 13 days, 29 played games' lines were first stored after
kickoff. sports_db keeps that late `lines_known_at`, and this repo's `lines_before_kickoff`
test failed on 58 team rows.

## Decision
`lines_before_kickoff` on `int_team_games` has severity `warn`.

## Why
- These are real pregame closing lines, stored late. Here, past games' lines only train the
  team volume model, which is exactly how closing lines are used in the backtest.
- Live projections use Kalshi, or nflverse lines stored before kickoff.
- A hard failure would block the weekly refresh for an operational gap, not a leak.

## Consequences
- The warning stays visible on every build until those rows age out of interest.
- If this repo ever builds a pregame table for others, it must drop lines with
  `lines_known_at >= kickoff_utc` and fail on them, as sports_db's marts will.
