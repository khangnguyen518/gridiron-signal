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
blend               = w x ours + (1 - w) x Sleeper + median shift + matchup, per position
Questionable        = blend x chance to play x production if playing, by last practice
range, win prob     = 1,000 simulated games per player, mixed with history (10th-90th percentile)
```

## Results (walk-forward, test seasons 2019-2025)

| Model | MAE | Within-week rank corr | Close calls right |
|---|---|---|---|
| Sleeper | 4.560 | 0.571 | 54.2% |
| Points share (baseline) | 4.856 | 0.516 | 52.9% |
| Opportunity (ours) | 4.617 | 0.553 | 54.0% |
| Blend, before the median shift and matchup term | 4.511 | 0.576 | 54.7% |
| **Blend: opportunity + Sleeper (live)** | **4.456** | **0.577** | **54.9%** |

- The blend beats Sleeper by about 2.3% (MAE 4.456 vs 4.560). Before the matchup term, the gap is -0.102, with a 95% interval of -0.120 to -0.084 from a paired week bootstrap. The gap is real at every position. The blend is ahead in all 7 test seasons and clearly ahead in 6. The 2024 gap is within noise (p = 0.20).
- The median shift after blending cut MAE by 0.054 and left every start/sit order unchanged (decision 0016).
- Questionable players were the largest error in real start/sit calls. Discounting them by chance to play and production picks the right player in about 10 more of every 100 close calls that involve one (decision 0017).
- Depth chart roles were the largest single gain: each player's share is pulled toward what his role (WR1, RB1, ...) gets on his team, which captures how each offense spreads the ball (a WR1 gets 17% of targets in some offenses, 32% in others; an RB1 37% to 73% of carries).
- Renormalizing shares by who is expected to play cut our model's MAE by 1.4%. On teams with a fresh key absence, our model alone now matches Sleeper, and the blend beats it by 1.3%.
- QB gains most: a backup QB now inherits the starter's volume. Our model alone is ahead of Sleeper at QB (5.99 vs 6.07 on start-worthy QBs), but not yet beyond noise (p = 0.07).
- On close start/sit calls the blend is right 54.9% of the time vs Sleeper's 54.2%. The edge is small, but its interval excludes zero (+0.30 to +1.04 points). It comes from players below starter level. Among weekly starters the blend is more accurate but no better at ordering them, so for start/sit between two starters, follow Sleeper's order except at QB.
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
uv run nflm league --discord      # post the summary to the Discord webhook too
uv run nflm refresh               # check sports_db is fresh, then dbt build (cron on the VM)
uv run nflm refresh --force       # build even if sports_db did not build in the last 30 hours
uv run nflm record-lines          # append a snapshot of Kalshi lines and player props (hourly cron on the VM)
uv run nflm log-projections       # append this week's live projections for the forward test (cron on the VM)
uv run nflm backtest              # tune, walk-forward test, write output/backtests/<timestamp>/ and model/model_card.json
uv run nflm backtest --skip-tune  # reuse the last tuned params
uv run nflm sim-backtest          # tune and test the ranges, rerun after every backtest
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
- Injuries: Out, IR, suspended and bye players are zeroed and their usage goes to teammates (Doubtful counts as out for teammates too). Questionable players are discounted by their chance to play, but their teammates do not yet absorb that missing share.
- Rookies before their first game, kickers and defenses use Sleeper's projection.
- Kicker and defense ranges are assumed, not backtested. QB ranges cover 75% instead of 80%.

## Next steps

1. Model who specifically replaces an absent starter, and let teammates absorb a Questionable player's expected missing share
2. Line-movement features from the recorded Kalshi history (recording since 2026-10-22)
3. Read the 2026 forward test at the end of the regular season (decision 0019)
