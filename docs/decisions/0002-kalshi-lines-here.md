# 0002. Kalshi lines live here, not in sports_db

- Status: Accepted
- Date: 2026-10-21

## Context
nflverse lines in sports_db are closing lines and arrive only when sports_db loads. Live weeks
need current lines. Kalshi lists NFL spread and total ladders through a public API.

## Decision
- `lines.py` reads open `KXNFLSPREAD` and `KXNFLTOTAL` markets at run time.
- The line is where the mid price crosses 50% on each ladder, interpolated between strikes.
- Kalshi lines are used for live weeks only. Backtests use nflverse closing lines.
- Nothing from Kalshi is stored in BigQuery yet.

## Why
- Kalshi data is not CC0 or CC BY, so it fails sports_db's source rule (sports_db decision 0013).
- A ladder's 50% point is the market's median, which is what a spread or total means.

## Consequences
- No Kalshi history yet, so line-movement features cannot be backtested. Kalshi NFL game markets
  only go back to about 2025.
- If Kalshi is down, the latest nflverse line is used and a note is printed.
