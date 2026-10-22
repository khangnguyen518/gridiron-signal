# 0007. Project stat lines, score with each league's settings

- Status: Accepted
- Date: 2026-10-21

## Context
Leagues differ in scoring: PPR level, passing TD points, TE premium.

## Decision
- The model projects stats (targets, yards, TDs, ...), never points directly.
- `scoring.fantasy_points` applies a Sleeper `scoring_settings` dict, including position
  reception bonuses. Sleeper's projections are scored with the same dict.
- Backtest actuals are computed from nflverse stat lines with the same function.

## Why
- One projection serves every league.
- Our computed actuals match Sleeper's league-scored actuals with a mean gap of 0.03 points,
  so the target is the same thing Sleeper is judged on, and it exists before 2018 too.

## Consequences
- Yardage bonuses and two-point conversions are not projected.
- Blend weights were fit on full-PPR scoring.
