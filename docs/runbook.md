# Runbook

## Weekly refresh (before setting a lineup)

1. **Load new games into sports_db** (writes sports_db raw, builds its dev staging):
   ```bash
   cd ~/projects/sports_db && uv run python -m ingestion.pipelines.daily
   ```
   If its dbt step fails, the loads still landed. Fix sports_db, or at least rebuild the
   play-by-play table: `cd dbt && uv run dbt run --select stg_nflverse__pbp --target dev`.
   The other staging models this repo reads are views over raw and update by themselves.
2. **Rebuild this repo's tables:**
   ```bash
   cd ~/projects/gridiron-signal/dbt && set -a && source ../.env && set +a && uv run dbt build --profiles-dir .
   ```
   Expect every test to pass, or the `lines_before_kickoff` warning described in `docs/data.md`.
3. **Run the league tool with fresh data:**
   ```bash
   cd ~/projects/gridiron-signal && uv run nflm league --refresh
   ```
   The "Stats end at week N" note should be gone.

## Retuning (once a season, or after a model change)

```bash
uv run nflm backtest              # about 2 minutes on cached data
uv run nflm backtest --skip-tune  # reuse the last tuned params, refit weights only
```

Compare `output/backtests/<new>/summary.csv` with `docs/backtest.md` and update that doc.
The newest run with a `model_card.json` becomes the live model.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "No backtest found" | no `model_card.json` in `output/backtests/` | `uv run nflm backtest` |
| "Pick your team with --user" | no user given or name not found | use a display name from the printed list |
| "Stats end at week N" | sports_db not loaded recently | weekly refresh steps 1-3 |
| "Kalshi lines unavailable" | Kalshi API error | nothing; nflverse lines are used |
| Lines: some games "from none" | game has no Kalshi market and no nflverse line yet | those teams' players get no projection of ours; Sleeper's is used |
| dbt "Invalid project ID '{{ env_var(...) }}'" | `env_var` inside `vars` is not rendered in sources | put `env_var()` directly in `_sources.yml` (already done) |
| BigQuery auth errors | expired ADC | `gcloud auth application-default login` |
| Python sees old data after `dbt build` | Parquet cache | add `--refresh`, or delete `data/cache/` |
| Teammate projections changed a lot overnight | Sleeper changed someone's injury status | expected: renormalization moved usage; check the `*_scale` columns in `all_projections.csv` |
| A player is missing from projections | no NFL game yet, not QB/RB/WR/TE, or not in the crosswalk | check `int_player_xwalk` for his Sleeper ID |

## Housekeeping
- `output/` and `data/cache/` are gitignored and safe to delete. Deleting `output/backtests/`
  removes the live model card until the next backtest.
- Sleeper asks that `/v1/players/nfl` be called at most once a day; the cache handles that.
