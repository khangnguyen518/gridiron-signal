# Backtest

Method, results and findings for the run behind the current model card
(`output/backtests/20261021_224714/`, the same model as `20261021_210351` rerun with
`--skip-tune` to add intervals). Rerun with `uv run nflm backtest`.

## Method

| Step | Seasons | Purpose |
|---|---|---|
| Warm-up | 2010-2011 | feature history only, never scored |
| Tuning | 2012-2017 | half-lives and shrinkage, by MAE of the opportunity projection |
| Availability tuning | 2016-2018 | renormalization strength (roster status is complete from 2016) |
| Blend start | 2018 | first season with Sleeper projections, used only to fit weights |
| Test | 2019-2025 | walk-forward: each season uses only earlier seasons |

For each test season S:
1. Team volume models fit on team-games from seasons before S.
2. Every played player game in S with at least one earlier game gets a projection.
3. Shares are renormalized by who was expected to play (variants below).
4. Blend weight per position is the 0.05-grid value with the lowest MAE on 2018 to S-1.

Three variants are scored on the same rows:
- `none`: no availability adjustment (the model before 2026-10-21).
- `lock`: expected to play = on the game-day active list and not Out.
- `midweek`: expected to play = on the roster and not Out or Doubtful. **The live model.**

Rows scored: player games where the player played and Sleeper had a projection (35,389).
"Relevant" rows also need a Sleeper projection of at least 5 points (23,024).

### Metrics
- **MAE**: mean absolute error in fantasy points (full PPR, 4-point passing TD).
- **Rank corr**: mean Spearman correlation between projection and actual within each position and week.
- **Close-call accuracy**: among same-position, same-week pairs of relevant players that Sleeper
  projects within 2 points of each other, the share where the higher-projected player scored
  more (about 187,000 pairs). This is the start/sit question.
- **Fresh key absence**: players whose team is missing someone who played the team's previous
  game and holds at least 15% of targets, 30% of carries or 50% of attempts (lock flags, so the
  same 4,942 relevant rows for `none` and `lock`).
- **Intervals** (`significance.py`): every comparison is a gap between two projections on the
  same rows (MAE of a minus MAE of b; close-call accuracy of a minus b). The 95% interval and
  p-value come from a paired bootstrap that resamples whole weeks (124 test weeks, 2,000
  resamples, fixed seed). Weeks, not rows, because players in the same week share game
  outcomes: treating 35,000 rows as independent makes almost any gap look real. The p-value is
  twice the share of resamples on the far side of zero, so `0.000` means under 1 in 2,000.

## Results, 2019-2025 (midweek, the live model)

| Model | MAE all | MAE relevant | Rank corr (all) | Close calls |
|---|---|---|---|---|
| Sleeper | 4.560 | 5.613 | 0.571 | 54.2% |
| Points share | 4.856 | 5.780 | 0.516 | 52.9% |
| Opportunity | 4.662 | 5.632 | 0.551 | 53.7% |
| Blend: points share + Sleeper | 4.539 | 5.573 | 0.572 | 54.5% |
| **Blend: opportunity + Sleeper** | **4.525** | **5.554** | **0.575** | **54.7%** |

### Availability adjustment: before and after

| | none | lock | midweek |
|---|---|---|---|
| Opportunity MAE, all rows | 4.726 | 4.681 | **4.662** |
| Opportunity MAE, relevant | 5.698 | 5.645 | **5.632** |
| Blend MAE, all rows | 4.535 | 4.529 | **4.525** |
| Close calls (blend) | 54.4% | **54.7%** | 54.7% |
| Seasons the blend beats Sleeper | 4 / 7 | 5 / 7 | **6 / 7** |

**Fresh key absence (4,942 relevant rows):**

| | Sleeper | Opportunity, none | Opportunity, lock | Blend, none | Blend, lock |
|---|---|---|---|---|---|
| MAE | 5.531 | 5.637 | **5.530** | 5.471 | **5.458** |
| Bias | +0.40 | -1.03 | -0.43 | -0.16 | 0.00 |
| QB MAE | 6.045 | 6.244 | **5.918** | 5.946 | **5.841** |
| RB MAE | 5.648 | 5.907 | 5.712 | 5.615 | 5.608 |

### By position (MAE, relevant rows, midweek)

| Model | QB | RB | WR | TE |
|---|---|---|---|---|
| Sleeper | 6.074 | 5.602 | 5.726 | 4.858 |
| Opportunity | 5.990 | 5.740 | 5.714 | 4.871 |
| Blend | 5.922 | 5.581 | 5.674 | 4.813 |

### By season (MAE, all rows, midweek)

| Season | Sleeper | Opportunity | Blend | Blend wins |
|---|---|---|---|---|
| 2019 | 4.912 | 4.901 | 4.804 | yes |
| 2020 | 4.776 | 4.952 | 4.769 | yes |
| 2021 | 4.785 | 4.752 | 4.683 | yes |
| 2022 | 4.453 | 4.616 | 4.452 | yes, by 0.001 |
| 2023 | 4.343 | 4.475 | 4.327 | yes |
| 2024 | 4.397 | 4.582 | 4.407 | no |
| 2025 | 4.337 | 4.427 | 4.308 | yes |

### Is it noise? Week-bootstrap intervals

Gap = a minus b. For MAE, negative favors a; for close calls, positive favors a.

| a vs b | Rows | Metric | Gap | 95% interval | p |
|---|---|---|---|---|---|
| Blend vs Sleeper | all | MAE | -0.034 | -0.047 to -0.023 | <0.001 |
| Blend vs Sleeper | relevant | MAE | -0.058 | -0.075 to -0.043 | <0.001 |
| Blend vs Sleeper | relevant | close calls | +0.48 pts | +0.13 to +0.84 | 0.006 |
| Opportunity vs Sleeper | all | MAE | +0.103 | +0.076 to +0.130 | <0.001 |
| Opportunity vs Sleeper | relevant | MAE | +0.020 | -0.015 to +0.055 | 0.25 |
| Blend vs points-share blend | all | MAE | -0.014 | -0.022 to -0.004 | 0.005 |
| Blend vs points-share blend | relevant | close calls | +0.17 pts | -0.18 to +0.52 | 0.33 |
| Midweek vs none, opportunity | all | MAE | -0.064 | -0.073 to -0.054 | <0.001 |
| Midweek vs none, blend | all | MAE | -0.010 | -0.014 to -0.006 | <0.001 |
| Midweek vs none, blend | relevant | close calls | +0.26 pts | +0.09 to +0.45 | 0.002 |
| Midweek vs lock, blend | all | MAE | -0.003 | -0.005 to -0.002 | <0.001 |
| Midweek vs lock, blend | relevant | close calls | -0.07 pts | -0.19 to +0.04 | 0.18 |

**Blend vs Sleeper by position** (relevant rows):

| Position | MAE gap | 95% interval | Close-call gap | 95% interval |
|---|---|---|---|---|
| QB | -0.152 | -0.234 to -0.079 | +0.84 pts | -0.41 to +2.05 |
| RB | -0.020 | -0.030 to -0.010 | +0.78 pts | +0.31 to +1.22 |
| WR | -0.052 | -0.071 to -0.034 | +0.34 pts | -0.13 to +0.83 |
| TE | -0.045 | -0.067 to -0.023 | +0.38 pts | -0.44 to +1.23 |

Our model alone vs Sleeper at QB, relevant rows: -0.084 MAE, interval -0.186 to +0.006, p = 0.07.

**Blend vs Sleeper by season** (all rows):

| Season | Gap | 95% interval | p |
|---|---|---|---|
| 2019 | -0.108 | -0.141 to -0.075 | <0.001 |
| 2020 | -0.007 | -0.037 to +0.021 | 0.61 |
| 2021 | -0.102 | -0.130 to -0.073 | <0.001 |
| 2022 | -0.001 | -0.018 to +0.018 | 0.94 |
| 2023 | -0.016 | -0.033 to +0.002 | 0.07 |
| 2024 | +0.010 | -0.004 to +0.025 | 0.15 |
| 2025 | -0.028 | -0.048 to -0.007 | 0.01 |

`significance.csv` has 286 comparisons, and many are significant. Read the rows above first:
with that many tests, a few small p-values will be luck. The intervals hold blend weights and
tuned parameters fixed, so they slightly understate the full uncertainty.

## What the results say

- **The availability adjustment is the model's first clear gain.** It cuts the opportunity
  model's MAE by 1.4% and its bias on teams with a fresh absence from -1.03 to -0.43 points.
  On those teams our model alone now matches Sleeper, and the blend beats Sleeper by 1.3%.
- **QB is where it matters most.** When a starting QB is out, the backup now inherits the
  starter's volume. The blend's biggest edge over Sleeper is at QB (-0.15 MAE on relevant rows,
  clearly real). Our model alone is ahead of Sleeper at QB (5.990 vs 6.074) but that is not
  yet distinguishable from noise (p = 0.07).
- **The blend beats Sleeper by about 0.8% overall, and the gap is real** (interval -0.047 to
  -0.023, excluding zero). It is clearly ahead in 3 of 7 seasons (2019, 2021, 2025) and
  indistinguishable from Sleeper in the other 4: "6 of 7 seasons" overstates it. The close-call
  edge (54.7% vs 54.2%) is small but real, and comes mostly from RB.
- **Midweek beats lock on MAE by a real but tiny margin** (0.003). Lock's close-call lead is
  noise (p = 0.18). Midweek is the live model because live projections only know the injury report.
- **Sleeper is still hard to beat at RB.** The blend weight on our model is 0.15.
- **The QB weight still falls over time**, 0.95 in 2019 to 0.60 in 2025, as Sleeper's QB
  projections improve.
- **The simple baseline blends nearly as well** (4.539 vs 4.525), so averaging two different
  forecasts is still part of the gain. The opportunity model's extra 0.014 is real on MAE,
  but not on close calls.

### Blend weights by test season (midweek, weight on opportunity)

| Position | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| QB | 0.95 | 0.90 | 0.75 | 0.75 | 0.70 | 0.65 | 0.60 |
| RB | 0.25 | 0.15 | 0.15 | 0.20 | 0.20 | 0.20 | 0.15 |
| WR | 0.25 | 0.40 | 0.35 | 0.45 | 0.40 | 0.40 | 0.35 |
| TE | 0.40 | 0.45 | 0.35 | 0.40 | 0.40 | 0.40 | 0.40 |

## Tuning findings

### Half-lives and shrinkage (2012-2017, 324 settings)

Best MAE of the opportunity projection for each value, holding the others at their best:

| Usage half-life | 1 | 1.5 | **2** | 3 | 4 | 6 | 8 | 12 |
|---|---|---|---|---|---|---|---|---|
| MAE | 4.697 | 4.666 | **4.658** | 4.662 | 4.672 | 4.695 | 4.715 | 4.746 |

| Efficiency half-life | 1 | 2 | **3** | 4 | 6 | 8 | 16 | 32 |
|---|---|---|---|---|---|---|---|---|
| MAE | 4.665 | 4.660 | **4.658** | 4.659 | 4.660 | 4.661 | 4.665 | 4.668 |

| Shrinkage multiplier | 0.125 | 0.25 | **0.5** | 1 | 2 |
|---|---|---|---|---|---|
| MAE | 4.661 | 4.660 | **4.658** | 4.659 | 4.661 |

| Team half-life | 2 | 4 | **8** | 16 | 32 |
|---|---|---|---|---|---|
| MAE | 4.664 | 4.659 | **4.658** | 4.660 | 4.661 |

- **Usage should be very recent:** a 2-game half-life. A 12-game window costs almost 0.09 points.
- Efficiency, shrinkage and team volume barely matter: every value is within 0.01.
- The first grid put the best values on its edge, so it was widened until every best value was inside.

### Availability strength (2016-2018, 125 settings per variant, midweek shown)

Off: 4.6338. Best: 4.5932.

| beta | 0 | 0.25 | 0.5 | 0.75 | 1 |
|---|---|---|---|---|---|
| targets | 4.6139 | 4.5963 | **4.5932** | 4.6053 | 4.6298 |
| carries | 4.6043 | 4.5976 | 4.5938 | **4.5932** | 4.5965 |
| QB attempts | 4.5958 | 4.5946 | 4.5939 | **4.5932** | 4.5938 |

Partial adjustment is best: vacated usage is not fully absorbed by players with history
(new signings and rookies take some of it).

## Ranges (game simulation), 2019-2025

`uv run nflm sim-backtest`, run behind `output/sim_backtests/20261022_003430/`. Projections from
the live model; quantiles at the 10th, 25th, 50th, 75th and 90th percentiles; 39,280 player games.

| Step | Seasons | Chooses |
|---|---|---|
| Game script | 2012-2017 | pass and rush attempt slopes on margin deviation |
| Calibration | 2016-2018 | kappa, eta, yards noise (36 settings), then tail stretch per position |
| Mix | 2017-2018 | weight on the simulation vs history, per position |
| Test | 2019-2025 | nothing; scored only |

**Pinball loss** is the average quantile loss over the five percentiles (lower is better, a proper
score for ranges). **Coverage**: the 10-90 range should hold 80% of outcomes, 25-75 should hold 50%.

| Ranges | Pinball | 10-90 coverage | 25-75 coverage | Below p10 | Above p90 |
|---|---|---|---|---|---|
| **Mixed (live)** | **1.5369** | 79.7% | 50.6% | 10.0% | 10.4% |
| History only (residual baseline) | 1.5419 | 80.0% | 50.6% | 10.3% | 9.8% |
| Simulation, tails stretched | 1.5453 | 81.9% | 55.3% | 6.5% | 11.6% |
| Simulation only | 1.5465 | 80.3% | 54.1% | 7.9% | 11.8% |
| Mixed, centered on the blend, live code path | 1.5677 | 81.4% | 51.5% | 8.1% | 10.5% |

By position (mixed): QB 76.7% coverage, RB 82.4%, WR 78.5%, TE 80.4%.

The last row runs exactly the live transform (`mix_with_residuals`) with a history table built only
from 2016-2018, centered on the blend (35,386 rows with a Sleeper projection). Its pinball loss is
higher because the blend rows are a different set; its coverage is what matters there.

**What this says:**
- **Mixing beats either source alone.** The simulation knows each player's situation (volume,
  touchdown dependence); history knows how projections miss in practice. The average of their
  quantiles scores better than both.
- **QB ranges come from history.** The simulation made QBs too narrow (17% of games below its 10th
  percentile): it misses busts like injuries, benchings and blowouts that end early. History alone
  scored best for QBs, and even it covers only 77%: QB outcomes have fat tails.
- **Correlation is the simulation's real contribution.** A QB and his top receiver correlate 0.40 in
  the simulation and 0.32 in real games (2023-2025, after the live transforms): the right sign and
  size, slightly too strong. History alone has no correlation at all, and win probability needs it.
- **Typical 10-90 width (simulation):** QB 19.7 points, RB 13.9, WR 14.6, TE 10.8.

## Things tried and dropped

| Idea | Result | Why |
|---|---|---|
| Linear calibration per position before blending | blend MAE 4.551 vs 4.535 | Least squares moves projections toward the mean; fantasy points are right-skewed and MAE rewards the median. |
| Availability with QB attempt shares summed | beta for attempts tuned to 0 (no help) | Backups keep big shares from old spot starts, so the sum is misleading. Replaced by the top QB's share. |
| Vacated targets spread across all positions | 4.604 vs 4.596 (2016-2018) | A missing WR's targets mostly go to other WRs. Replaced by position groups. |
| League-median usual totals per position | blend 4.528 vs 4.525 | Pushed teams toward league style (a pocket QB got 1.74x carries). Replaced by each team's own usual. |
| Simulation ranges alone | pinball 1.5453 vs 1.5369 mixed | Too narrow at QB, too few big games overall. Kept for correlation, mixed with history for each player's range. |

## Output files

| File | Contents |
|---|---|
| `tuning_grid.csv` | every half-life and shrinkage setting with opportunity and points-share MAE |
| `renorm_grid.csv` | every availability strength setting, per variant |
| `params.json` | chosen half-lives and shrinkage |
| `blend_weights.csv` | weight per position, test season and variant |
| `mae_by_season.csv` | MAE per model, season and variant |
| `summary.csv` | every metric by row set, position, model and variant |
| `summary_key_absence.csv` | the same for players on teams with a fresh key absence |
| `significance.csv` | week-bootstrap gap, 95% interval and p-value per comparison, row set, position and season |
| `model_card.json` | params, live variant's betas and usual-total factors, blend weights |

`nflm league` uses the newest run folder that has a `model_card.json`.

Simulation outputs (`output/sim_backtests/<run>/`): `calibration_grid.csv` (every setting) and
`ranges.csv` (every row above, by position).

## Next steps that could move these numbers
1. Discount Questionable players, and model who specifically replaces an absent starter.
2. Simulate games for score distributions, then optimize win probability.
3. Kalshi price history for midweek line movement.
