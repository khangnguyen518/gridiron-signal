# gridiron-signal

Weekly fantasy projections built top-down from betting lines and player usage,
blended with Sleeper's projections, plus a Sleeper league tool for start/sit and
waiver decisions.

The Python package is `nfl_model` and the command is `nflm`.

Reads from two sibling projects and never writes to them:
- **sports_db**: nflverse stats, play-by-play, schedules and closing lines (BigQuery `dev_staging`)
- **fantasy-football-draft-helper**: Sleeper projections and league-scored actuals (BigQuery `ff_marts`)

Live lines come from Kalshi's public spread and total markets.

## How a projection is built

```
team implied points = (total + spread) / 2          closing line, or live Kalshi ladder
team volume         = linear fit on implied points, spread, team's recent volume
player usage        = team volume x player's recent share (targets, carries, attempts)
                      x availability scale: shares renormalized over who is expected to play
                      pulled toward his team's usual share for his depth chart role (WR1, RB1, ...)
player stats        = usage x efficiency shrunk toward the position average
player TDs          = team TDs x red-zone share
points              = the league's own scoring_settings applied to the stat line
blend               = w x ours + (1 - w) x Sleeper, w per position
range, win prob     = 1,000 simulated games per player, mixed with history (10th-90th percentile)
```

## Results (walk-forward, test seasons 2019-2025)

| Model | MAE | Within-week rank corr | Close calls right |
|---|---|---|---|
| Sleeper | 4.560 | 0.571 | 54.2% |
| Points share (baseline) | 4.856 | 0.516 | 52.9% |
| Opportunity (ours) | 4.617 | 0.553 | 54.0% |
| **Blend: opportunity + Sleeper** | **4.511** | **0.576** | **54.7%** |

- The blend beats Sleeper by about 1.1% (MAE gap -0.048, 95% interval -0.063 to -0.036, from a paired week bootstrap), and the gap is real at every position. By season it is clearly ahead in 3 of 7 and statistically tied in the other 4.
- Depth chart roles were the largest single gain: each player's share is pulled toward what his role (WR1, RB1, ...) gets on his team, which captures how each offense spreads the ball (a WR1 gets 17% of targets in some offenses, 32% in others; an RB1 37% to 73% of carries).
- Renormalizing shares by who is expected to play cut our model's MAE by 1.4%. On teams with a fresh key absence, our model alone now matches Sleeper, and the blend beats it by 1.3%.
- QB gains most: a backup QB now inherits the starter's volume. Our model alone is ahead of Sleeper at QB (5.99 vs 6.07 on start-worthy QBs), but not yet beyond noise (p = 0.07).
- On close start/sit calls the blend is right 54.7% of the time vs Sleeper's 54.2%: small, but the interval excludes zero (+0.16 to +0.87 points).
- Team play calling (neutral-situation pass rate, pace, the opponent's run/pass tendencies faced) and red-zone rates improve rushing projections; the same inputs made receiver projections worse, so passing keeps the line-based inputs.
- Usage needs a short memory: a 2-game half-life beats 12 games by almost 0.09 points of MAE.
- Each player's 80% range holds 79.1% of outcomes (2019-2025). Mixing the game simulation with history beats either alone, and the simulation's correlations drive matchup win probability.

Full method and findings: [docs/backtest.md](docs/backtest.md).

## Setup

```bash
uv sync
cp .env.example .env          # set SLEEPER_LEAGUE_ID and SLEEPER_USERNAME
gcloud auth application-default login
cd dbt && set -a && source ../.env && set +a && uv run dbt build --profiles-dir . && cd ..
uv run nflm backtest          # writes the model card the league tool needs
```

## Commands

```bash
uv run nflm league                # this week's lineup, close calls, waiver targets
uv run nflm league --week 8 --user "display name"
uv run nflm league --refresh      # re-read BigQuery after new stats load
uv run nflm refresh               # check sports_db is fresh, then dbt build (cron on the VM)
uv run nflm record-lines          # append a snapshot of Kalshi NFL lines (hourly cron on the VM)
uv run nflm backtest              # tune, walk-forward test, write output/backtests/<timestamp>/
uv run nflm backtest --skip-tune  # reuse the last tuned params
uv run pytest
```

## Documentation

| Doc | What's in it |
|---|---|
| [AGENTS.md](AGENTS.md) | rules for people and AI agents working here |
| [docs/architecture.md](docs/architecture.md) | data flow, layers, entry points, configuration |
| [docs/data.md](docs/data.md) | sources, dbt models, coverage, data gotchas |
| [docs/model.md](docs/model.md) | every formula, tuned parameters, blend weights |
| [docs/backtest.md](docs/backtest.md) | method, results by position and season, tuning findings |
| [docs/league-tool.md](docs/league-tool.md) | `nflm league` usage, output, rules, Kalshi lines |
| [docs/runbook.md](docs/runbook.md) | weekly refresh, retuning, troubleshooting |
| [deploy/README.md](deploy/README.md) | daily refresh and Discord lineup posts on the shared VM |
| [docs/decisions/](docs/decisions/README.md) | why each design choice was made |

## Known limits

- Usage is only as fresh as sports_db's last load. The CLI warns when it lags.
- Injuries: Out, IR, suspended and bye players are zeroed and their usage goes to teammates (Doubtful also counts as out for teammates). Questionable players are not discounted.
- Rookies before their first game, kickers and defenses use Sleeper's projection.
- Kicker and defense ranges are assumed, not backtested. QB ranges cover 77% instead of 80%.

## Next steps

1. Discount Questionable players; model who specifically replaces an absent starter
2. Line-movement features from the recorded Kalshi history (recording since 2026-10-22)
