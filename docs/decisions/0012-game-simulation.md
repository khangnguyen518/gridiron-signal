# 0012. Simulate games for ranges and win probability, mixed with history

- Status: Accepted
- Date: 2026-10-22

## Context
Projections were expected points only. Start/sit decisions depend on the spread of outcomes and
on how players move together: an underdog needs upside, and a QB and his receiver boom together.
Close calls were near coin flips on expected points alone.

## Decision
- `simulate.py` plays every game 1,000 times live: margin and total around the line, game script,
  Dirichlet usage splits, per-play yardage noise, team touchdowns shared between a QB and his
  receivers. Draws are centered on the projection in use.
- Each player's range is the average of the simulation's quantiles and history's (the projection
  plus past misses for that position and projection level), weighted per position: QB 0, RB 0.5,
  WR 0.5, TE 0.75. The mix is a rank-preserving transform, so the simulation's correlations stay.
- The league tool shows the 10th to 90th percentile, matchup win probability from shared draws,
  and the bench swaps that raise win probability.
- Settings are tuned on 2012-2018 by pinball loss (`nflm sim-backtest`) and stored in the model card.

## Why
- On 2019-2025 the mixed ranges scored best (pinball 1.5369 vs 1.5419 history only and 1.5453
  simulation only) with 79.7% of outcomes inside the 80% range.
- History alone has no correlation between players, and win probability depends on it.
- The simulation alone was too narrow at QB; history alone fixed that.

## Consequences
- The model card carries a 2,000-number table of historical misses.
- Kicker and defense ranges are assumed, not backtested, and independent of their games.
- QB ranges cover 77% instead of 80%: QB outcomes have fatter tails than either source captures.
- The lineup post uses about 145 MB more memory.
