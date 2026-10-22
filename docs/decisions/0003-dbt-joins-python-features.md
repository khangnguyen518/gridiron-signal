# 0003. dbt for joins, Python for recency features

- Status: Accepted
- Date: 2026-10-21

## Context
Features are exponentially weighted sums with tuned half-lives. Tuning tries 324 settings.

## Decision
- dbt builds the set-based tables: team games with lines, player games with red-zone counts,
  the crosswalk, and the joined input table.
- Python computes every recency-weighted feature, fits the models, and runs the backtest.
- Python caches the dbt tables as Parquet.

## Why
- Recomputing features in SQL for each setting would mean hundreds of BigQuery queries.
  In pandas the whole grid runs in about 2 minutes from cache.
- One feature function serves both the backtest and live projections.

## Consequences
- Features are not stored in BigQuery. Anyone wanting them runs Python.
- The cache must be refreshed (`--refresh`) after `dbt build`.
