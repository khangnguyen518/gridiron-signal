# AGENTS.md

## Project
Weekly NFL fantasy projections built top-down from betting lines and player usage,
blended with Sleeper's projections, plus a Sleeper league tool for start/sit and waivers.
Audience: the owner, for personal fantasy decisions and as a portfolio project.

Read `docs/architecture.md` before changing structure and `docs/model.md` before changing
features or the projection math. Each rule below links to a record in `docs/decisions/`.
A change that breaks a decision needs a new record first.

## Stack
- Python 3.12 (`.python-version`), managed with uv. `uv.lock` is committed.
- Warehouse: BigQuery. This repo writes only to `NFLM_GCP_PROJECT.NFLM_DATASET` (default `gen-lang-client-0525946386.nflm_dev`).
- Transform: dbt Core with dbt-bigquery, in `dbt/`. Features and models: pandas and scikit-learn, in `src/nfl_model/`. (0003)
- Auth: Application Default Credentials. No key files.
- Lint: ruff. Test: pytest.

## Sources (0001, 0002)
- **sports_db** (`~/projects/sports_db`): nflverse staging in `SPORTS_DB_STAGING` (default `dev_staging`), plus `raw_nfl.rosters_weekly` for Sleeper IDs only. Read only.
- **fantasy-football-draft-helper**: Sleeper weekly projections and league-scored actuals in `ff_marts`. Read only.
- **Sleeper public API**: league, rosters, users, projections, players (cached a day), trending adds.
- **Kalshi public API**: NFL spread, total and winner markets. Recorded hourly into `nflm_raw` and read live. Kept here, never loaded into sports_db.

## Repo map
- `dbt/models/intermediate/` team games with lines, player games, availability, Sleeper crosswalk
- `dbt/models/marts/`        `fct_player_game_inputs`, the model input table
- `src/nfl_model/features.py` recency-weighted shares and shrunk rates
- `src/nfl_model/availability.py` who is expected to play, share renormalization
- `src/nfl_model/model.py`    team volume models and the two projections
- `src/nfl_model/backtest.py` tuning, walk-forward test, model card
- `src/nfl_model/live.py`     projections for an upcoming week
- `src/nfl_model/league.py`   Sleeper lineup, close calls, waivers
- `src/nfl_model/lines.py`    Kalshi ladders to spread and total
- `src/nfl_model/sleeper.py`  Sleeper API
- `src/nfl_model/scoring.py`  league scoring
- `src/nfl_model/refresh.py`  scheduled refresh: sports_db freshness check, dbt build
- `src/nfl_model/alerts.py`   Discord alerts and lineup posts
- `src/nfl_model/record.py`   hourly Kalshi line recorder (0011)
- `model/model_card.json`     the live model (written by backtest, committed to deploy)
- `deploy/`                   VM setup scripts, crontab, VM runbook (0010)
- `tests/`                    pytest
- `docs/`                     architecture, data, model, backtest, league tool, runbook, decisions

## Commands
- Install: `uv sync`
- dbt: `cd dbt && set -a && source ../.env && set +a && uv run dbt build --profiles-dir .`
- Backtest: `uv run nflm backtest` (add `--skip-tune` to reuse the last tuned params, `--refresh` to re-read BigQuery)
- League: `uv run nflm league [--week N] [--user NAME] [--league-id ID] [--refresh] [--discord]`
- Refresh (cron on the VM): `uv run nflm refresh [--force]`
- Record Kalshi lines (cron on the VM, hourly): `uv run nflm record-lines`
- Test: `uv run pytest`
- Lint and format: `uv run ruff check src tests --fix && uv run ruff format src tests`

## Point-in-time rules
- A projection for game G uses only games before G. `features.lagged_wsum` excludes the current row. Keep it that way, and keep `tests/test_features.py` passing.
- Team volume models for season S fit on seasons before S (backtest) or games before the week's first kickoff (live).
- Tuned parameters come from 2012-2017 only; availability strength from 2016-2018. Blend weights for season S come from 2018 to S-1. (0005, 0009)
- "Expected to play" uses only pregame information: roster status, injury report known before kickoff, or Sleeper's injury status live. `played` adds placeholder rows and is never a feature. (0009)
- Lines in backtests are nflverse closing lines. Live weeks use Kalshi first. (0002, 0008)

## Modeling rules
- Projections are stat lines. Points always come from `scoring.fantasy_points` with the league's own settings. (0007)
- Do not add level calibration without beating the current blend's MAE in the backtest. (0006)
- Report a model change with the full `nflm backtest` summary, not one season or one position.
- A tuned value on the edge of its grid means the grid is too narrow. Widen it and rerun.

## Data rules
- Never write to sports_db or the draft helper's datasets.
- `nflm_raw` is append-only and shared by every environment. Never update, delete or truncate it. (0011)
- Select named columns from sports_db raw tables. Never `select *` from raw.
- A Sleeper ID that maps to two gsis IDs, or the reverse, is dropped, never guessed. (0004)

## Secrets
- `.env` holds config and your league ID. It is gitignored. Never print it.
- No API keys are needed. Sleeper and Kalshi reads are public.

## Git
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.
- Generated outputs stay in `output/` and `data/cache/`, both gitignored.
- `model/model_card.json` is committed on purpose: committing it deploys a new model to the VM.

## Environments (0010)
- Laptops: dbt target `dev`, dataset `nflm_dev`, reading sports_db `dev_staging`.
- The VM: target `prod`, dataset `nflm`, reading sports_db `staging`. Never build `prod` from a laptop
  except to test a deploy change.

## How to work
- Before editing, list the plan in 3 to 5 bullets and the files you will touch.
- After changing features or the model: `uv run pytest`, then `uv run nflm backtest`, then compare with `docs/backtest.md`.
- After changing dbt: `dbt build` and check that every test passes or warns for a documented reason.
- Update the docs in `docs/` in the same change.
