# 0004. Sleeper to gsis crosswalk from nflverse weekly rosters

- Status: Accepted
- Date: 2026-10-21

## Context
Sleeper projections and leagues use Sleeper player IDs. nflverse stats use `gsis_id`.
Sleeper's own `gsis_id` field is filled for only about 960 of 3,047 active skill players.

## Decision
- `int_player_xwalk` maps IDs from `raw_nfl.rosters_weekly`, which carries `sleeper_id`.
  sports_db staging drops that column, so this is the one raw read.
- Only one-to-one pairs are kept. Ambiguous IDs are dropped.
- Live projections fall back to Sleeper's own `gsis_id` for players missing from the map.

## Why
- Matches all but 1 to 5 of about 4,900 played player-weeks per season, 2018-2025.
- Name matching would be guesswork.

## Consequences
- The raw read must select named columns only (sports_db cost rule).
- A player new to nflverse rosters is unmatched until the next roster load.
