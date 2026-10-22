# 0005. Tune on 2012-2017, walk-forward test on 2019-2025

- Status: Accepted
- Date: 2026-10-21

## Context
Half-lives, shrinkage and blend weights are all chosen from data. Choosing them on the seasons
that are also scored makes results look better than real use.

## Decision
- 2010-2011: feature warm-up only.
- 2012-2017: tune half-lives and shrinkage on the opportunity projection's MAE.
- 2018: first Sleeper season, used only to fit blend weights.
- 2019-2025: each test season fits team volume and blend weights on earlier seasons only.
- Live weights come from all of 2018-2025.

## Why
- Test seasons never influence tuned parameters.
- Sleeper's projections are not needed to tune the model itself, so tuning can use older seasons.

## Consequences
- Tuned values reflect 2012-2017 football. Retune if the league's style shifts.
- 2019's blend weight comes from one season of Sleeper data.
