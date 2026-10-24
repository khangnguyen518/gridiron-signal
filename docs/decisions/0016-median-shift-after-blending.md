# 0016. Shift the blend to the median, per position

- Status: Accepted
- Date: 2026-10-24
- Amends: 0006

## Context
0006 rejected a least-squares calibration (actual ~ a + b x projection) because it pulls toward
the mean of right-skewed fantasy points, while MAE rewards the median, and asked that any future
calibration be a median fit that beats the blend. On 2026-10-23, while testing target quality and
game script against the blend's misses, a constant fitted on earlier seasons by median regression
explained more of the miss than either feature family (MAE -0.051 on 2020-2025).

## Decision
- After blending, add one constant per position: the median of (actual - blend) on the same
  earlier seasons the weight is picked on (2018 to S-1 in the backtest, 2018-2025 live).
- The weight is picked first, exactly as before, then the shift at that weight. A constant per
  position cannot reorder players within it, so start/sit order and close calls do not change.
- Rows with only one projection (rookies with no NFL game, kickers, defenses) are not shifted:
  the shift was fit on blended rows.
- Ranges and win probabilities stay centered on the blend before the shift. The simulation sets
  each player's mean, and the shifted blend estimates the median, which sits below it. Centering
  on the shifted blend dropped 10-90 coverage from 81.1% to 69.4% (12.4% of outcomes above p90).
- The model card stores it as `positions.<POS>.shift`. Cards without it mean a shift of 0.
- The backtest keeps the old blend as `blend_unshifted`, so every run measures the shift.

## Why
- Full backtest, 2019-2025 (`20261024_000432`), shifted vs unshifted blend: MAE -0.054 on all
  rows (-0.063 to -0.044), -0.048 on relevant rows, -0.029 on startable rows (-0.045 to -0.014),
  week-bootstrap 95% intervals. Six of seven seasons improve clearly; 2023 is borderline (p = 0.08).
- The blend now beats Sleeper in all seven seasons (2024 was a loss: 4.410 vs 4.397, now 4.371).
- Picking the weight and the shift together gained about as much MAE but moved the weights (QB
  0.60 to 0.50) and cost 0.12 points of startable close-call accuracy (p = 0.07). Weight first
  avoids that.

## Consequences
- Projections now sit about 0.9 points below average actual points (bias -0.98 on all rows, was
  -0.28). That is the point: they estimate the median outcome, which is below the mean.
- The shift does not help QBs (MAE +0.015 to +0.021, every interval includes 0). It is kept for
  QBs too: dropping it on the strength of the test seasons would be choosing on the test.
- Displayed projections are lower than Sleeper's by roughly the shift (0.5 to 0.8 points). Totals
  and matchup win probabilities shift the same way for both teams.
- The league tool shows the shifted projection; its 10th-90th percentile range comes from the
  unshifted center, so the projection sits slightly below the middle of the range.
