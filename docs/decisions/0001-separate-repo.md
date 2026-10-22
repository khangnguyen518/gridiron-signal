# 0001. A separate repo that reads sports_db and the draft helper

- Status: Accepted
- Date: 2026-10-21

## Context
sports_db is a product with strict rules: only redistributable sources, no betting lines in
product tables until reviewed, a decision record for each change. Modeling needs Kalshi lines,
Sleeper projections and fast iteration.

## Decision
- Models live in `~/projects/nfl-model`, with their own BigQuery dataset (`nflm_dev`).
- sports_db staging and the draft helper's marts are read only. Nothing here writes to them.

## Why
- Keeps sports_db clean for its users and licenses.
- The model can use any source a personal project may use.
- Portfolio story: one repo builds the warehouse, another builds models on it.

## Consequences
- Data freshness depends on sports_db's loader (see `docs/runbook.md`).
- A change in sports_db staging columns can break `dbt/models/intermediate/`.
- Features that sports_db's own rolling models will need are rebuilt here for now.
