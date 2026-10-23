# 0015. Record Kalshi player props hourly, append-only

- Status: Accepted
- Date: 2026-10-23
- Extends: 0011

## Context
Kalshi lists weekly NFL player props as ladders of binary markets: touchdowns (1+, 2+, 3+), first
touchdown, receiving, rushing and passing yards, receptions, attempts, completions, passing TDs,
interceptions, player and D/ST fantasy points, and team totals. On 2026-10-22 they were quoted on
both sides for every game, at about a 5-cent spread, with anytime touchdowns the deepest (about
1.2 million contracts traded). Prop markets are usually the strongest single predictor of a
player's stat line, but Kalshi's public API serves open markets only, so they cannot be backtested
without recording them first.

## Decision
- `nflm record-lines` also snapshots every open market in the series listed in `props.SERIES` and
  appends one row per market to `nflm_raw.kalshi_player_props`, in the same hourly run as the game
  lines (0011).
- A row keeps the raw observation: ticker, title, Kalshi's player ID, the player name and team
  parsed from the market, strike, bid, ask, last price, volume and open interest. No ladder math
  or gsis matching happens at record time.
- Props get their own table, not new columns on `kalshi_markets`: they are keyed by player, and
  game-line consumers stay unchanged.
- Game lines are recorded first, and a prop failure is caught and alerted on its own, so a problem
  with props never costs an hour of game lines.

## Why
- Raw rows keep every input, so matching and ladder math can be redone as they improve.
- One run and one table per kind keeps the VM unchanged: no new cron entry, and the existing
  `rawAppender` role already lets load jobs create the table.
- About 4,400 rows an hour at about 300 bytes is roughly 4 GB per season. It fits the free 10 GB
  of storage this season and costs about $0.02 a GB a month beyond it.

## Consequences
- History starts 2026-10-23. Using props in the model needs at least most of a season recorded.
- Players are matched by name and team only when the history is read. Kalshi's player ID is
  stored so a crosswalk can be built later, under the same rule as 0004: ambiguous matches are dropped.
- The prop pull adds about 3 seconds and 135 MB to each hourly run (measured on a laptop).
- Like 0011, snapshots after kickoff are recorded too; consumers must filter to pregame rows.
