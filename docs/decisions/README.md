# Decision records

One file per decision: what we chose, why, and what it costs.
A new decision gets the next number. A changed decision gets a new record that marks the old one `Superseded`.

## Status values
- `Accepted`: in effect.
- `Proposed`: open for discussion.
- `Superseded by NNNN`: replaced.

## Index
| # | Decision | Status |
|---|---|---|
| 0001 | A separate repo that reads sports_db and the draft helper | Accepted |
| 0002 | Kalshi lines live here, not in sports_db | Accepted |
| 0003 | dbt for joins, Python for recency features | Accepted |
| 0004 | Sleeper to gsis crosswalk from nflverse weekly rosters | Accepted |
| 0005 | Tune on 2012-2017, walk-forward test on 2019-2025 | Accepted |
| 0006 | No level calibration before blending | Accepted |
| 0007 | Project stat lines, score with each league's settings | Accepted |
| 0008 | Late-stored lines warn instead of failing | Accepted |
| 0009 | Renormalize usage shares by who is expected to play | Accepted |
| 0010 | Refresh on the shared loader VM, after sports_db | Accepted |

## Template
```
# NNNN. Title

- Status: Accepted
- Date: YYYY-MM-DD

## Context
## Decision
## Why
## Consequences
```
