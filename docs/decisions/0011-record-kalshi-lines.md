# 0011. Record Kalshi lines hourly, append-only

- Status: Accepted
- Date: 2026-10-22
- Amends: 0002
- Extended by: 0015 (player props), 0019 (live projection log)

## Context
Live projections read Kalshi's current lines, but nothing kept them. Line movement during the
week, midweek decisions, and Kalshi vs sportsbook comparisons all need history, and Kalshi's
public API serves open markets only. Every unrecorded hour is lost for good.

## Decision
- `nflm record-lines` snapshots every open market in `KXNFLSPREAD`, `KXNFLTOTAL` and `KXNFLGAME`
  and appends them to `nflm_raw.kalshi_markets`, plus the derived per-game line to
  `nflm_raw.kalshi_game_lines`. Hourly at :05 on the VM.
- Game lines use the same code as live projections (`lines.game_lines`), so history and live agree.
- `nflm_raw` is append-only and shared by laptops and the VM, like sports_db's raw datasets. The VM
  gets a custom `rawAppender` role there: it can append but never delete.
- dbt matches snapshots to nflverse games (`int_kalshi_game_lines`) and keeps the last pregame line
  per game (`fct_kalshi_closing_lines`).

## Why
- Raw market rows keep every input, so line math can be redone later. The derived rows make the
  common query cheap.
- Hourly keeps the closing snapshot within about an hour of kickoff. At about 700 rows an hour the
  cost is negligible (about 0.4 GB a season, load jobs free).
- Kalshi's terms are not CC0 or CC BY, so this stays out of sports_db (0002).

## Consequences
- History starts 2026-10-22. Backtests that need it have one partial season for now.
- A missed hour is a permanent gap. Failures post to Discord.
- Snapshots during games are recorded as well; consumers must use `is_pregame`.
