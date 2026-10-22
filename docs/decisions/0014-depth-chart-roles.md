# 0014. Depth chart roles and team role curves

- Status: Accepted
- Date: 2026-10-23

## Context
Each player's share came only from his own recent games. That misses three things: a player just
named a starter has little history in the role; offenses differ in how they spread the ball (some
feed their WR1 30% of targets, others 18%); and backfields range from workhorse (RB1 with 70% of
carries) to committee (40%).

## Decision
- `int_player_game_depth` gives each skill player's pregame depth tier (1 = starter): the weekly
  chart through 2024, the last daily snapshot before kickoff from 2025 (WR tier = ceil(rank / 3),
  since ranks run across the three receiver spots).
- Each week, a team's expected-to-play WRs, TEs and RBs are ranked within position by depth tier,
  then recent share: that rank is the role (WR1, WR2, RB1, ...).
- A team's role curve is the share each role actually got in its earlier games (half-life 8 team
  games). Each player's target and carry share is pulled toward his team's curve for his role
  with a pseudo-count of 2 games: (n x share + 2 x curve) / (n + 2), n = his recency-weighted games.
- Tuned on 2016-2018 by `nflm backtest` (`tune_roles`). Ranking by recent share alone was tested
  and lost (2016-2018 MAE 4.564 vs 4.548), so only the depth rule is searched.

## Why
- On 2019-2025 against the previous model (paired week bootstrap): our model's MAE fell 0.042
  (-0.054 to -0.030), with RB -0.054, WR -0.048 and TE -0.037; the blend's fell 0.014 (-0.018 to
  -0.009), and 0.021 on start-worthy players. The largest gain of any change so far.
- The blend now beats Sleeper by 0.048 MAE (-0.063 to -0.036), up from 0.035.
- Close-call accuracy did not move (+0.01 points, within noise): roles make projections more
  accurate overall but do not change coin-flip start/sit calls.

## Consequences
- Live projections load roster status and depth charts for history, and keep three seasons of
  history (position priors still use every season). A guard fails the run if a player-game appears
  twice: upcoming-week rosters load before kickoff, and placeholder rows for them once doubled
  every share.
- Depth charts are missing for about 9% of player-games before 2025; those players rank after
  everyone listed.
- QBs have no role curves (one starter per team; attempts are handled by renormalization).
