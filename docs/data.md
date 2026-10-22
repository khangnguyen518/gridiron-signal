# Data

Every table this repo builds, what it reads, and the data facts that are easy to get wrong.

## Sources read

| Source | Object | Used for |
|---|---|---|
| sports_db staging | `stg_nflverse__schedules` | games, kickoff, closing spread and total, `lines_known_at` |
| sports_db staging | `stg_nflverse__player_stats_week` | player box scores (regular season, QB/RB/WR/TE) |
| sports_db staging | `stg_nflverse__team_stats_week` | team pass attempts, sacks, carries, pass and rush TDs |
| sports_db staging | `stg_nflverse__pbp` | red-zone targets and carries (inside the 20, no two-point tries) |
| sports_db staging | `stg_nflverse__rosters_weekly` | weekly roster status (ACT, INA game-day inactive, RES, PUP, SUS) |
| sports_db staging | `stg_nflverse__injuries_history` | injury report status as known before kickoff |
| sports_db raw | `raw_nfl.rosters_weekly` | `sleeper_id` to `gsis_id`, which staging drops |
| draft helper | `int_weekly_projected_points` | Sleeper's projection, scored with the league's settings |
| draft helper | `int_weekly_actual_points` | Sleeper's league-scored actuals |

sports_db is nflverse data under CC BY 4.0. This repo is personal use. If any output is
ever shared, credit "Data: nflverse (CC BY 4.0)".

## dbt models (dataset `nflm_dev`)

### `int_team_games`
One row per team per regular-season game, 2010 onward, including future games (null stats).

| Column | Meaning |
|---|---|
| `game_id`, `season`, `week`, `kickoff_utc`, `team`, `opponent`, `is_home` | game keys |
| `spread` | expected margin from this team's side; positive means favored. nflverse `spread_line` is the home margin, so away rows flip it. |
| `total_line` | closing total |
| `implied_points` | `(total_line + spread) / 2` |
| `lines_known_at` | when sports_db first stored these line values |
| `points_scored` | final points, null before the game |
| `pass_attempts`, `sacks`, `rush_attempts`, `pass_tds`, `rush_tds` | team volume from `team_stats_week` |
| `rz_pass_attempts`, `rz_rush_attempts` | red-zone plays from play-by-play |

Tests: unique `(game_id, team)`; `lines_known_at` before kickoff (warns, see below).

### `int_player_games`
One row per QB, RB, WR or TE per regular-season game played, 2010 onward.
Box score columns (`pass_attempts` ... `fumbles_lost`) are nullable source values coalesced to 0.
`fumbles_lost` sums rushing, receiving and sack fumbles lost. `rz_targets` and `rz_carries`
come from play-by-play. Tests: unique `(game_id, gsis_id)`, `gsis_id` not null.

### `int_player_xwalk`
Sleeper `player_id` to nflverse `gsis_id`, from every weekly roster row with both IDs.
One-to-one: a Sleeper ID with two gsis IDs, or a gsis ID with two Sleeper IDs, is dropped.
Tests: both columns unique and not null. See decision 0004.

### `int_player_game_status`
One row per QB, RB, WR or TE on a team's weekly roster per regular-season game (statuses ACT,
INA, RES, PUP, SUS), 2010 onward: 141.8k rows.

| Column | Meaning |
|---|---|
| `roster_status` | nflverse weekly roster status |
| `injury_status` | last injury report status known before kickoff, or null |
| `expected_active_lock` | ACT and not Out: known after inactives post, about 90 minutes before kickoff |
| `expected_active_midweek` | ACT or INA, and not Out or Doubtful: the injury report alone |
| `played` | has a stat line in the game. An outcome, used only to add placeholder rows. |

Checked 2016-2025: INA players played 0% of the time; ACT players reported Out played 0.1%.
Test: unique `(game_id, gsis_id)`.

### `fct_player_game_inputs`
`int_player_games` joined to the team's row in `int_team_games` (columns prefixed `team_`)
and to Sleeper's projection and actual through the crosswalk. Sleeper columns are null before
2018 or for unmatched players. Test: unique `(game_id, gsis_id)`.

## Coverage (checked 2026-10-21)

| Item | Coverage |
|---|---|
| Player games | 86.7k rows, 2010 to 2026 week 6 |
| Lines | every regular-season game 2010 onward has a spread and total |
| Sleeper projection matched | 2018 onward; 3,363 of 5,188 player games in 2018 (65%), 84% to 92% each season 2019-2025 |
| Crosswalk | all but 1 to 5 of about 4,900 played player-weeks per season 2018-2025 |
| Scoring parity | our points from nflverse stats vs Sleeper's league-scored actuals: mean gap 0.03 points; 22 to 43 rows a season differ by more than 1 |

## Facts that are easy to get wrong

- **Roster status before 2016.** nflverse weekly rosters have no game-day `INA` status before 2016,
  and 18% of 2010-2015 player games have no roster row. Availability is tuned on 2016-2018 only.

- **Late lines.** If sports_db's loader misses game days, a played game's lines are first stored
  after kickoff. sports_db keeps that late `lines_known_at` on purpose. Here those rows only feed
  team-volume training as history, which is what closing lines are in the backtest, so the
  `lines_before_kickoff` test warns instead of failing (decision 0008). On 2026-10-21 that was
  29 games (58 team rows) in 2026 weeks 5 and 6.
- **Staleness.** Stats are only as fresh as sports_db's last daily load. `nflm league` prints a note
  when stats end before last week.
- **Team codes.** nflverse uses `LA` for the Rams and `JAX` for Jacksonville. Sleeper uses `LAR`;
  Kalshi uses `LAR` and `JAC`. Maps live in `sleeper.TEAM_TO_NFLVERSE` and `lines.NFLVERSE_TO_KALSHI`.
- **Sleeper's own `gsis_id`** is filled for only about a third of active skill players, so the
  crosswalk comes from nflverse rosters, with Sleeper's field as a fallback for new players.
- **Players who did not play** have no row in `int_player_games`. The backtest scores only games
  played; inactive players are not part of the error numbers.
- **Positions.** A player's position is nflverse's position in that game. Live rows use the
  player's last nflverse position, not Sleeper's.
- **Sleeper projections are backfilled.** They are probably Sleeper's final pregame version, which
  makes the benchmark slightly harder than what a user saw midweek.

## Local cache

`data/cache/` holds `player_games.parquet`, `team_games.parquet`, `xwalk.parquet`,
`player_status.parquet` and
`sleeper_players.json` (refreshed after 24 hours). Delete the folder or pass `--refresh` after
`dbt build` so Python sees new rows.
