# Architecture

How data moves from sources to a lineup recommendation, and where each piece runs.

## Data flow

```
sports_db (BigQuery, read only)         draft helper (BigQuery, read only)
  dev_staging: schedules, player stats,   ff_marts: Sleeper projected points,
  team stats, play-by-play, rosters,      league-scored actual points
  injuries history
  raw_nfl.rosters_weekly (sleeper_id)
            │                                       │
            └──────────────┬────────────────────────┘
                           ▼
   Kalshi API ──hourly, record.py──> nflm_raw (append-only): game lines, player props (props.py)
                           │
            dbt (this repo) -> nflm_dev
              int_team_games        team x game: lines, points, volume
              int_player_games      player x game: box score + red zone
              int_player_xwalk      Sleeper ID <-> gsis_id
              int_player_game_status  roster + injury status: who was expected to play
              int_kalshi_game_lines   recorded Kalshi snapshots matched to games
              fct_kalshi_closing_lines  last pregame Kalshi line vs nflverse
              fct_player_game_inputs  model input (player games + team + Sleeper)
                           │
                           ▼   data.py caches each table as Parquet in data/cache/
            Python (src/nfl_model)
              features.py   recency-weighted shares, shrunk rates   (point in time)
              availability.py  placeholder rows, share renormalization by who plays
              model.py      team volume models, two projections
              backtest.py   tune -> walk-forward test -> model_card.json
              significance.py  week-clustered bootstrap intervals on model gaps
                           │
                           ▼
              live.py       next week's projections   <── Kalshi lines (lines.py)
              simulate.py   1,000 simulated games: ranges, matchup win probability
              league.py     lineup, close calls, waivers <── Sleeper API (sleeper.py)
                           │
                           ▼
                     terminal + output/league/<run>/*.csv
```

## Layers

| Layer | Where | Holds | Rebuilt by |
|---|---|---|---|
| Sources | sports_db, draft helper | nflverse and Sleeper history | those repos' pipelines |
| Tables | `dbt/` -> BigQuery `nflm_dev` | joins, red-zone counts, crosswalk | `dbt build` |
| Cache | `data/cache/*.parquet` | local copies of the dbt tables, Sleeper players | first read, or `--refresh` |
| Features and models | `src/nfl_model/` | everything time-weighted or fit | every run, in memory |
| Model card | `model/model_card.json` (committed) and `output/backtests/<run>/` | tuned params, blend weights, availability settings | `nflm backtest` |
| Live | `live.py`, `league.py` | one week's projections and advice | `nflm league` |

The split between dbt and Python is decision 0003: dbt does set-based joins once, and
Python does the recency weighting, which the tuning loop recomputes hundreds of times.

## Where it runs

| Where | Target and dataset | Reads sports_db | Runs |
|---|---|---|---|
| Laptop | `dev`, `nflm_dev` | `dev_staging` | everything, by hand |
| `sports-vm` | `prod`, `nflm` | `staging` | `nflm record-lines` hourly, `nflm refresh` daily, `nflm league --discord` Sun and Thu |

See `deploy/README.md` and decision 0010.

## Entry points

**`nflm backtest`**
1. Load the cached tables and compute actual fantasy points from stat lines.
2. Tune half-lives and shrinkage on 2012-2017 (`tune`).
3. Add roster placeholder rows and build features (`build_features`).
4. For each availability variant, tune its strength on 2016-2018 (`tune_renorm`).
5. Project 2018-2025 with and without renormalization, fitting team volume on earlier seasons each time (`project_rows`).
6. Per position, test season and variant, pick the blend weight on earlier seasons (`evaluate`).
7. Write grids, weights, metrics and `model_card.json` to `output/backtests/<timestamp>/`.

**`nflm league`**
1. Read the league's scoring and slots from Sleeper.
2. Build placeholder rows for this week's games and run the same feature code (`live.project_week`).
3. Renormalize each team's shares over players Sleeper does not list as out.
4. Swap in Kalshi lines where Kalshi lists the game.
5. Blend with Sleeper's projection using the latest model card's weights, then simulate games
   for each player's range and the matchup win probability.
6. Pick the best lineup, list close calls and waiver targets, write CSVs.

The live path reuses the backtest code on purpose: a placeholder row with zero stats sits
after the player's real games, and `lagged_wsum` only looks backward, so live features are
built exactly like backtest features.

## External services

| Service | Used for | Auth | Failure behavior |
|---|---|---|---|
| BigQuery | dbt and table reads | ADC | commands stop; cached Parquet still works offline |
| Sleeper API | league, rosters, projections, players, trending | none | retried 4 times, then the command stops |
| Kalshi API | live spread and total ladders | none | falls back to nflverse lines, prints a note |

## Configuration

All settings come from `.env` through `src/nfl_model/config.py` (see `.env.example`).
dbt reads the same variables through `env_var()` in `dbt/profiles.yml` and `dbt/models/staging/_sources.yml`.

| Variable | Default | Meaning |
|---|---|---|
| `NFLM_GCP_PROJECT` | `gen-lang-client-0525946386` | project this repo writes to |
| `NFLM_DATASET` | `nflm_dev` | dataset this repo writes to (`nflm` on the VM) |
| `NFLM_DBT_TARGET` | `dev` | dbt target for `nflm refresh` (`prod` on the VM) |
| `NFLM_RAW_DATASET` | `nflm_raw` | append-only data this repo records (Kalshi), shared by every environment |
| `NFLM_ALERT_WEBHOOK_URL` / `NFLM_ALERT_SECRET` | none | Discord webhook, or the Secret Manager version holding it |
| `SPORTS_DB_PROJECT` | `sports-db-209650` | sports_db project |
| `SPORTS_DB_STAGING` | `dev_staging` | sports_db staging dataset to read |
| `FF_PROJECT` / `FF_MARTS` | `gen-lang-client-0525946386` / `ff_marts` | draft helper marts |
| `SLEEPER_LEAGUE_ID` | none | default league for `nflm league` |
| `SLEEPER_USERNAME` | none | your Sleeper display name in that league |

## Cost
- One full `dbt build` processes about 400 MB (play-by-play red-zone counts are most of it).
- Python reads the tables once and caches them, so backtests are free to rerun.
- `maximum_bytes_billed` caps any dbt query at 10 GB.
