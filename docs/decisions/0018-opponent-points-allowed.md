# 0018. Opponent points allowed by position, after the blend

- Status: Accepted
- Date: 2026-10-24
- Amends: 0016

## Context
The opposing defense enters the model through the betting lines (implied points), the opponent's
neutral pass rate faced (rush attempts) and its red-zone rates (rush TDs). Nothing says "this
defense gives up points to TEs". A one-off test on 2020-2025 (2026-10-24) checked three defense
signals against the blend's misses, each built from earlier games and relative to the opposing
players' own averages:

| Signal | MAE, relevant | Close calls, relevant | MAE, startable |
|---|---|---|---|
| Points allowed by position | -0.0043 (-0.0071 to -0.0015) | +0.18 pts (+0.04 to +0.30) | -0.0035 (-0.0075 to +0.0005) |
| Efficiency allowed (yards per target, catch rate, yards per carry) | -0.0007 (noise) | -0.03 pts | -0.0020 (noise) |
| Passing volume allowed | -0.0006 (noise) | +0.00 pts | +0.0011 (noise) |

## Decision
- `matchup.points_allowed`: for every player-game, fantasy points minus the player's own prior
  average (half-life 6 games); a defense's points allowed to a position is the recency-weighted
  mean over the opposing players at it in its earlier games (half-life 8, 4 pseudo-players of 0).
- After the blend and the median shift, add weight x the opponent's points allowed to the
  player's position. The weight is a median regression of the blend's misses on the signal,
  without an intercept so it never moves the shift's level: for season S fit on 2019 to S-1
  (2019 itself gets none), live on 2019-2025. Stored as `matchup.weight` in the model card.
- Rows with only one projection (rookies, kickers, defenses) are not adjusted, like the shift.
- The backtest keeps `blend_no_matchup` (the blend before this record) to measure it every run.
- Efficiency allowed and passing volume allowed are not added.

## Why
Full backtest `20261024_131032`, 2019-2025, blend with the matchup term vs `blend_no_matchup`,
week-bootstrap 95% intervals:

| Rows | MAE | Close calls |
|---|---|---|
| Relevant (Sleeper >= 5) | -0.0044 (-0.0073 to -0.0017) | +0.16 pts (+0.03 to +0.28) |
| Startable | -0.0035 (-0.0076 to +0.0005), p = 0.10 | +0.02 pts (noise) |
| All | -0.0013 (-0.0034 to +0.0006), p = 0.19 | |

- The weight is steady across seasons (0.26 fit on 2019 only, 0.17 by 2025; live 0.158).
- Small, and measured directly on fantasy points and start/sit accuracy out of sample, which the
  QB and coach target-preference test was not. Relevant-player close calls against Sleeper rise
  from +0.51 to +0.67 points.
- Live, the term is small: 0.14 points typical, -0.75 to +0.56 across week 7 of 2026.

## Consequences
- Five of six seasons improve slightly and none clearly; 2024 is slightly worse (+0.0034, p = 0.08).
  Expect a small, uneven effect, mostly for players below starter level.
- 0016 said the median shift was the only adjustment after blending; this adds a second, which
  depends on the matchup, not a level.
