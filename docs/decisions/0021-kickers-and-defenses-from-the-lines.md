# 0021. Kickers and team defenses as stat lines from the lines

- Status: Accepted
- Date: 2026-11-11
- Extends: 0007, 0016

## Context
Kickers and team defenses came straight from Sleeper, with assumed Normal ranges. A first test
(2026-11-11) found Sleeper barely ranks them: within-week rank correlation 0.26 for defenses and
0.10 for kickers, 2019-2025. A median regression of league points on two line inputs (defense:
opponent implied points and own spread; kicker: own implied points and spread) beat Sleeper on
startable MAE for both. That prototype predicted league points directly, against 0007.

The bar, set before building the stat-line version: beat Sleeper on startable MAE (each week's
top 12 by Sleeper) with an interval excluding zero, and not lose to the direct-points prototype
beyond noise.

## Decision
- dbt: `int_defense_games` and `int_kicker_games` hold each unit's stat line per game in Sleeper's
  definitions; `int_sleeper_kdef` holds Sleeper's K/DEF projections and league-scored actuals;
  `int_player_xwalk` now includes kickers (105 pairs; no skill-player pair changed).
- Defense: points allowed = opponent implied points + a residual from earlier seasons' misses, so
  the bracket scoring is averaged over a distribution; sacks, interceptions, fumble recoveries,
  forced fumbles, defensive and special-teams TDs, safeties, blocked kicks and special-teams
  fumble recoveries are Poisson regressions on the lines and recent rates (half-life 8, earlier
  games only, shrunk toward the league average of earlier games).
- Kicker (the team's slot): field goal attempts per distance band and extra point attempts are
  Poisson regressions on implied points and spread; makes use league rates by band. Live, the
  slot goes to the team's kicker with the highest Sleeper projection.
- Points come from the league's scoring, like every position. Blend with Sleeper and a median
  shift per position, picked as in 0016 on 2018 to S-1.
- Ranges: the model's own draws (residual quantiles, Poisson counts, binomial makes), widened or
  narrowed by a factor per position calibrated on 2015-2017 (defense 1.25, kicker 0.9), then
  moved so their mean is the blend before the shift.
- `nflm kdef-backtest` runs the test and writes the fits to the card under `kdef`, which
  `nflm backtest` keeps.

## Why
`nflm kdef-backtest` run `20261110_203858`, 2019-2025, against Sleeper's league-scored actuals:

| | Startable MAE vs Sleeper | Close calls, startable | vs prototype, startable MAE | 10-90 coverage |
|---|---|---|---|---|
| Defense (blend) | -0.109 (-0.161 to -0.056) | +0.5 pts (noise) | -0.011 (noise) | 78.5% |
| Kicker (blend) | -0.069 (-0.133 to -0.004) | +3.2 pts (+1.0 to +5.3) | +0.009 (+0.001 to +0.017) | 79.5% |

- Defense passes both parts of the bar, and beats the prototype on all rows (-0.019).
- Kicker beats Sleeper, but loses to the prototype by 0.009 points a week, an interval just above
  zero: it misses the second part of the bar as written. Accepted anyway by the owner (2026-11-11):
  the gap is 0.3% of the error (about 0.15 points a season), and the stat-line version follows
  0007, works for any league scoring and gives calibrated ranges, which the prototype cannot.
- Our defense alone beats Sleeper in all seven seasons, but blending still helps a little: the
  live weight on ours is 0.40 (kicker 0.90). The weight on ours fell from 1.0 in 2019 to 0.45 in
  2025 as Sleeper's defense projections improved. Sleeper's stored projections were probably
  updated after inactives (0017), which favors Sleeper here.
- A leak found by a test before any result was trusted: the shrinkage target first used every
  season's average. Fixed to earlier games only; results changed by less than 0.002.

## Evaluation on the 2026 forward test (fixed before any K/DEF data is logged)
K and DEF rows are already in `projection_snapshots` (0019). Same rule as 0019: last prod
snapshot before kickoff, the shown projection against league-scored actuals, top 12 per week by
Sleeper's live projection, against Sleeper's live projection, week-bootstrap intervals, read at the
end of the regular season. The first snapshot with these projections marks the start.

## Consequences
- Defense rebuild matches Sleeper exactly in 82% of 2018-2025 team-games and within 2 points in
  95.5% (kickers 99.4% exact); the remaining gap is minor special-teams stats.
- The middle 50% of the range covers 45% for both, a little narrow; the 10-90 range is calibrated.
- K/DEF draws are independent of the game simulation: a defense does not yet move with the
  opposing offense's simulated game. Win probability treats them as independent.
- New dbt models need a prod build on the VM (`nflm refresh --force`) and the card deployed.
