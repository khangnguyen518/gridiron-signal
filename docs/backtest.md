# Backtest

Method, results and findings for the run behind the current model card
(`output/backtests/20261022_172939/`: tuned parameters from `20261021_210351`, with team
play-calling and red-zone inputs (decision 0013) and depth chart roles (decision 0014); the same
model as `20261022_123842`, rerun to add the startable tier). Rerun with `uv run nflm backtest`.

## Method

| Step | Seasons | Purpose |
|---|---|---|
| Warm-up | 2010-2011 | feature history only, never scored |
| Tuning | 2012-2017 | half-lives and shrinkage, by MAE of the opportunity projection |
| Availability tuning | 2016-2018 | renormalization strength (roster status is complete from 2016), then roles |
| Blend start | 2018 | first season with Sleeper projections, used only to fit weights |
| Test | 2019-2025 | walk-forward: each season uses only earlier seasons |

For each test season S:
1. Team volume models fit on team-games from seasons before S.
2. Every played player game in S with at least one earlier game gets a projection.
3. Shares are renormalized by who was expected to play (variants below), then pulled toward the
   team's curve for each player's role (lock and midweek variants).
4. Blend weight per position is the 0.05-grid value with the lowest MAE on 2018 to S-1.

Three variants are scored on the same rows:
- `none`: no availability adjustment (the model before 2026-10-21).
- `lock`: expected to play = on the game-day active list and not Out.
- `midweek`: expected to play = on the roster and not Out or Doubtful. **The live model.**

Rows scored: player games where the player played and Sleeper had a projection (35,389).
"Relevant" rows also need a Sleeper projection of at least 5 points (23,024).
"Startable" rows are each week's top 12 QBs, 24 RBs, 36 WRs and 12 TEs by Sleeper projection,
the starters in a 12-team league (10,416). They are ranked among scored rows, so a player ruled
out after Sleeper projected him is not in the ranking.

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
| Opportunity | 4.617 | 5.589 | 0.553 | 54.0% |
| Blend: points share + Sleeper | 4.539 | 5.573 | 0.572 | 54.5% |
| **Blend: opportunity + Sleeper** | **4.511** | **5.533** | **0.576** | **54.7%** |

### Availability adjustment: before and after

| | none | lock | midweek |
|---|---|---|---|
| Opportunity MAE, all rows | 4.723 | 4.630 | **4.617** |
| Opportunity MAE, relevant | 5.695 | **5.587** | 5.589 |
| Blend MAE, all rows | 4.535 | 4.515 | **4.511** |
| Close calls (blend) | 54.5% | 54.6% | **54.7%** |

`none` has neither availability nor roles; `lock` and `midweek` have both.

**Fresh key absence (4,942 relevant rows):**

| | Sleeper | Opportunity, none | Opportunity, lock | Blend, none | Blend, lock |
|---|---|---|---|---|---|
| MAE | 5.531 | 5.635 | **5.499** | 5.470 | **5.443** |
| Bias | +0.40 | -1.06 | -0.69 | -0.17 | -0.13 |
| QB MAE | 6.045 | 6.250 | **5.918** | 5.946 | **5.841** |
| RB MAE | 5.648 | 5.897 | 5.627 | 5.613 | 5.588 |

### By position (MAE, relevant rows, midweek)

| Model | QB | RB | WR | TE |
|---|---|---|---|---|
| Sleeper | 6.074 | 5.602 | 5.726 | 4.858 |
| Opportunity | 5.991 | 5.664 | 5.665 | 4.850 |
| Blend | 5.924 | 5.561 | 5.643 | 4.789 |

### By season (MAE, all rows, midweek)

| Season | Sleeper | Opportunity | Blend | Blend wins |
|---|---|---|---|---|
| 2019 | 4.912 | 4.849 | 4.786 | yes |
| 2020 | 4.776 | 4.893 | 4.746 | yes |
| 2021 | 4.785 | 4.712 | 4.654 | yes |
| 2022 | 4.453 | 4.554 | 4.434 | yes |
| 2023 | 4.343 | 4.445 | 4.327 | yes |
| 2024 | 4.397 | 4.572 | 4.410 | no |
| 2025 | 4.337 | 4.363 | 4.293 | yes |

### Is it noise? Week-bootstrap intervals

Gap = a minus b. For MAE, negative favors a; for close calls, positive favors a.

| a vs b | Rows | Metric | Gap | 95% interval | p |
|---|---|---|---|---|---|
| Blend vs Sleeper | all | MAE | -0.048 | -0.063 to -0.036 | <0.001 |
| Blend vs Sleeper | relevant | MAE | -0.080 | -0.099 to -0.062 | <0.001 |
| Blend vs Sleeper | relevant | close calls | +0.51 pts | +0.12 to +0.89 | 0.008 |
| Opportunity vs Sleeper | all | MAE | +0.058 | +0.030 to +0.083 | <0.001 |
| Opportunity vs Sleeper | relevant | MAE | -0.024 | -0.061 to +0.013 | 0.18 |
| Blend vs points-share blend | all | MAE | -0.028 | -0.038 to -0.017 | <0.001 |
| Blend vs points-share blend | relevant | close calls | +0.21 pts | -0.18 to +0.57 | 0.32 |
| Midweek vs none, opportunity | all | MAE | -0.106 | -0.122 to -0.089 | <0.001 |
| Midweek vs none, blend | all | MAE | -0.024 | -0.030 to -0.017 | <0.001 |
| Midweek vs none, blend | relevant | close calls | +0.24 pts | -0.02 to +0.50 | 0.08 |
| Midweek vs lock, blend | all | MAE | -0.004 | -0.006 to -0.001 | 0.001 |
| Midweek vs lock, blend | relevant | close calls | +0.05 pts | -0.07 to +0.18 | 0.43 |

**Blend vs Sleeper by position** (relevant rows):

| Position | MAE gap | 95% interval | Close-call gap | 95% interval |
|---|---|---|---|---|
| QB | -0.150 | -0.232 to -0.075 | +0.92 pts | -0.31 to +2.10 |
| RB | -0.040 | -0.053 to -0.027 | +0.66 pts | +0.19 to +1.13 |
| WR | -0.083 | -0.107 to -0.062 | +0.50 pts | -0.03 to +1.04 |
| TE | -0.069 | -0.100 to -0.039 | -0.04 pts | -0.95 to +0.90 |

Our model alone vs Sleeper at QB, relevant rows: -0.083 MAE, interval -0.184 to +0.006, p = 0.07.

**Blend vs Sleeper by season** (all rows):

| Season | Gap | 95% interval | p |
|---|---|---|---|
| 2019 | -0.126 | -0.161 to -0.092 | <0.001 |
| 2020 | -0.030 | -0.062 to +0.002 | 0.06 |
| 2021 | -0.130 | -0.167 to -0.093 | <0.001 |
| 2022 | -0.019 | -0.042 to +0.003 | 0.10 |
| 2023 | -0.016 | -0.036 to +0.007 | 0.18 |
| 2024 | +0.013 | -0.006 to +0.033 | 0.17 |
| 2025 | -0.043 | -0.065 to -0.021 | <0.001 |

### Startable players (weekly top 12 QB, 24 RB, 36 WR, 12 TE by Sleeper)

| Model | MAE | Bias | Rank corr | Close calls |
|---|---|---|---|---|
| Sleeper | 6.374 | +0.46 | 0.262 | **54.1%** |
| Opportunity | 6.374 | -0.96 | 0.224 | 52.2% |
| Blend: points share + Sleeper | 6.331 | +0.25 | 0.263 | 54.1% |
| **Blend: opportunity + Sleeper** | **6.300** | -0.21 | **0.264** | 53.6% |

About 58,000 close pairs. Rank correlation is low because every player here is already a starter.

| Blend vs Sleeper | MAE gap | 95% interval | Close-call gap | 95% interval |
|---|---|---|---|---|
| All | -0.074 | -0.100 to -0.048 | -0.45 pts | -1.18 to +0.24 |
| QB | -0.199 | -0.316 to -0.083 | +2.18 pts | -0.27 to +4.62 |
| RB | -0.042 | -0.063 to -0.021 | +0.05 pts | -0.73 to +0.91 |
| WR | -0.057 | -0.086 to -0.029 | **-1.01 pts** | -2.00 to -0.06 |
| TE | -0.065 | -0.119 to -0.013 | +0.02 pts | -1.97 to +2.12 |

Our model alone vs Sleeper on startable rows: MAE -0.001 (-0.051 to +0.050), close calls
-1.89 pts (-2.91 to -0.90). At QB alone it beats Sleeper on MAE: -0.177 (-0.316 to -0.045).

`significance.csv` has 416 comparisons, and many are significant. Read the rows above first:
with that many tests, a few small p-values will be luck. The intervals hold blend weights and
tuned parameters fixed, so they slightly understate the full uncertainty.

## What the results say

- **Among startable players the blend is more accurate, but not better at start/sit.** Its MAE
  is clearly lower than Sleeper's (-0.074) at every position, yet its close-call accuracy is
  53.6% vs 54.1% (not significant overall, p = 0.20), and it is significantly worse at WR
  (-1.0 points). Our model alone is clearly worse at ordering starters (-1.9 points). The
  relevant-row close-call edge comes from players below starter level. For start/sit between
  two starters, follow Sleeper's order; the exception is QB, where the blend leads on both
  measures (close calls not yet significant, p = 0.10).
- **Depth chart roles are the largest single gain** (decision 0014; section below): our model's MAE
  fell 0.042 and the blend's 0.014, with every position except QB better.
- **The availability adjustment was the model's first clear gain.** It cuts the opportunity
  model's MAE by 1.4% and its bias on teams with a fresh absence from -1.06 to -0.46 points.
  On those teams our model alone now matches Sleeper, and the blend beats Sleeper by 1.3%.
- **QB is where it matters most.** When a starting QB is out, the backup now inherits the
  starter's volume. The blend's biggest edge over Sleeper is at QB (-0.15 MAE on relevant rows,
  clearly real). Our model alone is ahead of Sleeper at QB (5.991 vs 6.074) but that is not
  yet distinguishable from noise (p = 0.07).
- **The blend beats Sleeper by about 1.1% overall, and the gap is real** (interval -0.063 to
  -0.036, excluding zero). It is clearly ahead in 3 of 7 seasons (2019, 2021, 2025) and
  indistinguishable from Sleeper in the other 4: "6 of 7 seasons" overstates it. The close-call
  edge (54.7% vs 54.2%, +0.51 points) is small but real, and comes mostly from RB. The MAE edge
  is now real at every position.
- **Midweek beats lock on MAE by a real but tiny margin** (0.004). Their close-call difference is
  noise (p = 0.43). Midweek is the live model because live projections only know the injury report.
- **Sleeper is still hardest to beat at RB**: the blend weight on our model there is 0.20, against
  0.45 for WRs and TEs after roles.
- **The QB weight still falls over time**, 0.95 in 2019 to 0.60 in 2025, as Sleeper's QB
  projections improve.
- **The simple baseline no longer blends nearly as well** (4.539 vs 4.511): the opportunity
  model's extra 0.028 is real on MAE,
  but not on close calls.

### Blend weights by test season (midweek, weight on opportunity)

| Position | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| QB | 0.95 | 0.90 | 0.80 | 0.75 | 0.70 | 0.70 | 0.60 |
| RB | 0.25 | 0.20 | 0.25 | 0.25 | 0.25 | 0.25 | 0.20 |
| WR | 0.25 | 0.45 | 0.40 | 0.55 | 0.50 | 0.45 | 0.45 |
| TE | 0.50 | 0.50 | 0.45 | 0.50 | 0.50 | 0.45 | 0.45 |

## Depth chart roles (decision 0014)

Each week, a team's expected-to-play WRs, TEs and RBs are ranked by depth chart tier, then recent
share (WR1, WR2, RB1, ...). Each team's role curve is what each role got in its earlier games; each
player's share is pulled toward his role's curve with a pseudo-count of 2 games.

**Chosen on 2016-2018** (opportunity MAE, after renormalization; no roles: 4.5903):

| Ranking | Curve half-life 4 | 8 | 16 |
|---|---|---|---|
| Depth tier, then share | 4.5488 | **4.5483** | 4.5485 |
| Recent share only | 4.5690 | 4.5664 | 4.5643 |

| Pull (games) | 0 | 0.5 | 1 | **2** | 4 | 8 | 16 |
|---|---|---|---|---|---|---|---|
| Carries (targets at 2) | 4.5544 | 4.5508 | 4.5492 | **4.5483** | 4.5491 | 4.5523 | 4.5560 |

The depth chart matters: the same curves with share-only ranking were clearly worse.

**2019-2025, roles vs none, paired week bootstrap** (same availability renormalization both sides):

| | MAE gap | 95% interval |
|---|---|---|
| Opportunity, all | -0.042 | -0.054 to -0.030 |
| Opportunity, RB / WR / TE | -0.054 / -0.048 / -0.037 | all below zero |
| Blend, all | -0.014 | -0.018 to -0.009 |
| Blend, relevant | -0.021 | -0.027 to -0.016 |
| Close calls, blend, relevant | +0.01 pts | -0.19 to +0.20 |

What the curves look like in 2026 week 7: WR1 share of team targets from 17% (CHI) to 32% (SEA);
RB1 share of carries from 37% (NE, a committee) to 73% (IND, a workhorse).

## Team style and red zone (decision 0013)

Added 2026-10-23: each team's neutral-situation pass rate (1st and 2nd down, quarters 1-3, score
within 7), plays per game, red-zone pass rate and touchdown rates, the opponent defense's same rates,
and a head-coach adjustment. Inputs were chosen per target on 2013-2018 and only then scored on
2019-2025.

**Team level, 2019-2025** (MAE per team-game; each season fit on earlier seasons):

| Target | Lines only | Chosen on 2013-2018 |
|---|---|---|
| Pass attempts | 6.286 | 6.286 (no new inputs; they scored 6.292 here) |
| Rush attempts | 5.852 | **5.814** |
| Pass TDs | 0.899 | 0.899 (no new inputs; they scored 0.894 here) |
| Rush TDs | 0.733 | **0.730** |

**Player level, 2019-2025, paired week bootstrap (new minus old, MAE):**

| | Gap | 95% interval | p |
|---|---|---|---|
| Opportunity, all | -0.0031 | -0.0046 to -0.0017 | <0.001 |
| Opportunity, RB | -0.0110 | -0.0161 to -0.0060 | <0.001 |
| Opportunity, WR / TE | -0.0003 / -0.0004 | just below zero | 0.03 / 0.02 |
| Opportunity, QB | -0.0002 | -0.0044 to +0.0037 | 0.97 |
| Blend, all | -0.0004 | -0.0011 to +0.0004 | 0.31 |
| Blend, RB | -0.0025 | -0.0046 to -0.0004 | 0.01 |

- **Play calling and red-zone rates help rushing projections**, mostly RBs. The blend's overall
  change is within noise.
- **Adding them to passing hurt receivers.** With new inputs for every target, QBs (-0.025) and
  RBs (-0.006) improved but WRs (+0.006) and TEs (+0.005) got significantly worse, and the blend
  netted zero. The per-target choice on 2013-2018 kept passing on the original inputs.
- **The head-coach adjustment barely matters**: the best pseudo-count on 2013-2018 was 2 games, and
  it moved 2019-2025 team MAE by under 0.001. An 8-game team half-life already adapts quickly.
- Building this exposed a data bug: play-by-play uses today's codes for relocated teams, so
  red-zone totals for STL, SD and OAK seasons had been zero (`docs/data.md`).

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

`uv run nflm sim-backtest`, run behind `output/sim_backtests/20261022_124018/`. Projections from
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
| **Mixed (live)** | **1.5306** | 79.1% | 50.1% | 10.5% | 10.4% |
| History only (residual baseline) | 1.5347 | 79.9% | 50.5% | 10.3% | 9.8% |
| Simulation, tails stretched | 1.5378 | 82.0% | 55.8% | 7.0% | 11.0% |
| Simulation only | 1.5407 | 80.7% | 54.6% | 7.2% | 12.1% |
| Mixed, centered on the blend, live code path | 1.5638 | 81.1% | 51.9% | 8.7% | 10.2% |

By position (mixed): QB 75.1% coverage, RB 80.5%, WR 78.2%, TE 81.1%.

The last row runs exactly the live transform (`mix_with_residuals`) with a history table built only
from 2016-2018, centered on the blend (35,386 rows with a Sleeper projection). Its pinball loss is
higher because the blend rows are a different set; its coverage is what matters there.

**What this says:**
- **Mixing beats either source alone.** The simulation knows each player's situation (volume,
  touchdown dependence); history knows how projections miss in practice. The average of their
  quantiles scores better than both.
- **QB ranges lean on history.** The simulation makes QBs too narrow (15-17% of games below its
  10th percentile): it misses busts like injuries, benchings and blowouts that end early. QB ranges
  are 75% simulation-free (weight 0.25) and still cover only 75%: QB outcomes have fat tails.
- **Correlation is the simulation's real contribution.** A QB and his top receiver correlate 0.40 in
  the simulation and 0.33 in real games (2023-2025, after the live transforms): the right sign and
  size, slightly too strong. History alone has no correlation at all, and win probability needs it.
- **Typical 10-90 width (simulation):** QB 19.8 points, RB 13.6, WR 14.2, TE 10.9.
- **With roles, the simulation earns more weight** in the mix (RB and WR 0.75, TE 0.5, QB 0.25):
  its usage splits now follow each team's role curves.

## Things tried and dropped

| Idea | Result | Why |
|---|---|---|
| Linear calibration per position before blending | blend MAE 4.551 vs 4.535 | Least squares moves projections toward the mean; fantasy points are right-skewed and MAE rewards the median. |
| Availability with QB attempt shares summed | beta for attempts tuned to 0 (no help) | Backups keep big shares from old spot starts, so the sum is misleading. Replaced by the top QB's share. |
| Vacated targets spread across all positions | 4.604 vs 4.596 (2016-2018) | A missing WR's targets mostly go to other WRs. Replaced by position groups. |
| League-median usual totals per position | blend 4.528 vs 4.525 | Pushed teams toward league style (a pocket QB got 1.74x carries). Replaced by each team's own usual. |
| Simulation ranges alone | pinball 1.5407 vs 1.5306 mixed | Too narrow at QB, too few big games overall. Kept for correlation, mixed with history for each player's range. |
| Opponent coverage (man vs zone) x receiver's past man/zone split, as an adjustment to WR and TE projections (one-off analysis, 2026-10-22, nflverse participation coverage labels 2018-2025, not loaded anywhere) | Sleeper's misses vs predicted edge, slope -0.37 (-1.43 to +0.71) for the efficiency split and -0.03 (-0.72 to +0.65) for the target-share split; out of sample (fit 2019-2021, test 2022-2025) MAE change +0.0002 and -0.0008, both noise | League-wide, man coverage costs WRs about 0.08 points per target against zone after adjusting for situation (lower catch rate, more TDs). A receiver's man/zone efficiency split does not repeat (season to season r = +0.06); his target-share split does (r = +0.33) but is about 3 points of share, so even a defense that plays 10 points more man than average moves him by under 0.2 points. The coverage data is CC BY-SA and excluded from sports_db; using it as a model input would need its own decision record. |

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
| `model_card.json` | params, live variant's betas and usual-total factors, blend weights; keeps `sim`, `sim_tails`, `range_mix` and `residual_table` from the previous card (warns to rerun `nflm sim-backtest` if the model changed) |

`nflm league` uses the newest run folder that has a `model_card.json`.

Simulation outputs (`output/sim_backtests/<run>/`): `calibration_grid.csv` (every setting) and
`ranges.csv` (every row above, by position).

## Next steps that could move these numbers
1. Discount Questionable players, and model who specifically replaces an absent starter.
2. Simulate games for score distributions, then optimize win probability.
3. Kalshi price history for midweek line movement.
