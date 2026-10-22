# 0006. No level calibration before blending

- Status: Accepted
- Date: 2026-10-21

## Context
The opportunity model runs about 0.8 points low for QBs. A per-position linear calibration
(actual ~ a + b x projection, fit on earlier seasons) looked like an easy fix.

## Decision
Blend the raw opportunity projection with Sleeper. No calibration step.

## Why
- Calibration raised blend MAE from 4.535 to 4.551 and standalone MAE from 4.726 to 4.817.
- Least squares moves projections toward the mean. Fantasy points are right-skewed, and MAE
  rewards the median, so a slight under-projection is close to MAE-optimal.

## Consequences
- Projections sit a little below average actual points by design (bias about -0.2).
- A future calibration should be a median (quantile) fit and must beat 4.535.
