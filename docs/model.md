# Model

How a projection is computed, with the code location of each step.

## Overview

```
team implied points  = (total + spread) / 2
team volume (4 fits) = f(implied points, spread, team's recent volume)       model.py
player usage         = team volume x player's recent share                   features.py
                       x availability scale (who else plays this week)       availability.py
player stat line     = usage x efficiency shrunk to the position average
player TDs           = team TDs x red-zone share
points               = league scoring on the stat line                       scoring.py
blend                = w x ours + (1 - w) x Sleeper, w per position          backtest.py
```

Two projections are built. **Points share** is a one-line baseline. **Opportunity** is the
real model. Each is also blended with Sleeper.

## Recency weighting (`features.lagged_wsum`)

Every player and team feature is an exponentially weighted sum over earlier games only:

```
S_g = sum over earlier games i of  lambda^(g - 1 - i) * x_i,   lambda = 0.5^(1 / half_life)
```

The previous game has weight 1, the game `half_life` games back has weight 0.5. Weights count
games played, not calendar weeks, and carry across seasons. It is vectorized as
`lambda^i * cumsum(x * lambda^-i)` per group, which stays finite for 300+ game careers.

**No leakage:** the current game's value is subtracted out, so changing a game's stats never
changes that game's features (`tests/test_features.py`).

## Usage shares (half-life `hl_share`)

| Feature | Formula |
|---|---|
| `target_share` | S(targets) / S(team pass attempts) |
| `carry_share` | S(carries) / S(team rush attempts) |
| `att_share` | S(pass attempts) / S(team pass attempts), about 1 for a starting QB |
| `rz_target_share` | (S(rz targets) + k_rz x target_share) / (S(team rz pass attempts) + k_rz) |
| `rz_carry_share` | (S(rz carries) + k_rz x carry_share) / (S(team rz rush attempts) + k_rz) |
| `points_share` | S(fantasy points) / S(team points) |

Shares are ratios of weighted sums, not averages of weekly ratios, so a 2-target week in a
20-attempt game counts less than a 2-target week in a 50-attempt game. Team totals come from
the player's own games, so a share is always relative to the team he played for.

## Availability renormalization (`availability.py`)

A recent share says nothing about who else plays this week. Each team-game's shares are
rescaled so the players **expected to play** add up to what the team usually spreads.

| Share | Group | S (now) | Usual |
|---|---|---|---|
| targets | RB, WR, TE separately | sum of shares of players at that position expected to play | team's recent share of targets to that position x stale-share factor |
| carries | RB | same | same, for carries |
| pass attempts | QBs | top attempt share among QBs expected to play | a usual starter's share (0.988) |

```
scale = clip((usual / S) ^ beta)       targets, carries: clip 0.5-2;  attempts: 0.5-40
```

- **Team's own usual.** `add_team_usual` takes, for each team and position group, the
  recency-weighted fraction of team targets (carries) that went to that group in earlier games
  (half-life `hl_team`). A team that throws to its TEs keeps doing so; nobody is pushed toward
  the league average. An earlier version used league medians and, for example, gave a pocket QB
  1.74x carries because his team rarely runs its QB.
- **Stale-share factor.** S runs higher than the true fraction because shares come from each
  player's own games (a returning WR still carries his old share). The factor is the median of
  S / usual over 2016-2018: WR 1.09, RB 1.12, TE 1.14 for targets; RB 1.08 for carries.
- **Within the position group.** A missing WR's targets go to the other WRs. Spreading them
  over all positions tuned worse (MAE 4.604 vs 4.596 on 2016-2018).
- **QBs use the top share, not a sum.** Backups keep big shares from old spot starts, so a sum
  is misleading. With the top share, a backup with 4% of attempts becomes the starter when the
  starter is out. QB carries are not adjusted: a backup does not inherit the starter's rushing.
- **No double counting.** A player out for a few games is already absorbed by his teammates'
  recent shares, so S is near usual and the scale is near 1. Returning starters push S above
  usual and scale teammates down.
- **Red-zone shares** scale with their base share.
- **Expected to play.** Backtest: from nflverse roster status and the injury report known before
  kickoff (`int_player_game_status`), in two versions:
  - `lock`: on the game-day active list and not Out (what you know after inactives post).
  - `midweek`: on the roster and not Out or Doubtful (what the injury report alone says).
  Live: Sleeper's injury status, with Out, IR, PUP, Sus, NA, DNR and Doubtful as not playing,
  which matches `midweek`. The live model uses the midweek settings.
- **Placeholder rows.** A rostered player who did not play gets a row with `played = 0`, so his
  share counts in S. `lagged_wsum`'s `step` keeps such rows from adding to or aging his history.

## Efficiency (half-life `hl_eff`, shrinkage `k`)

```
rate = (S(numerator) + k x prior) / (S(denominator) + k)
```

| Rate | Numerator / denominator | Base k |
|---|---|---|
| `catch_rate` | receptions / targets | 40 |
| `yds_per_target` | receiving yards / targets | 40 |
| `yds_per_carry` | rushing yards / carries | 60 |
| `yds_per_att` | passing yards / pass attempts | 150 |
| `int_rate` | interceptions / pass attempts | 150 |

Every k is multiplied by `k_mult`. Priors (`features.season_priors`) are position rates over
all seasons **before** the projected season. Passing priors come from QBs for every position.
Fumbles use the position prior rate only (per target plus carry).

## Team volume (`model.fit_volume_models`)

One linear regression per team stat, fit on played team-games from seasons before the projected one:

| Target | Inputs |
|---|---|
| pass attempts | implied points, spread, team's recent pass attempts |
| rush attempts | implied points, spread, team's recent rush attempts |
| pass TDs | implied points x team's recent pass share of TDs |
| rush TDs | implied points x (1 - that share) |

"Recent" is a weighted per-game average with half-life `hl_team`. The spread carries game
script: favorites run more, underdogs throw more. Predictions are clipped at 0.

## Opportunity projection (`model.project`)

```
targets      = team pass attempts x target_share
receptions   = targets x catch_rate
rec yards    = targets x yds_per_target
rec TDs      = team pass TDs x rz_target_share
carries      = team rush attempts x carry_share
rush yards   = carries x yds_per_carry
rush TDs     = team rush TDs x rz_carry_share
pass att     = team pass attempts x att_share
pass yards   = pass att x yds_per_att
pass TDs     = team pass TDs x att_share
INTs         = pass att x int_rate
fumbles lost = (targets + carries) x position fumble rate
```

Points come from `scoring.fantasy_points` with the league's `scoring_settings`. Two-point
conversions and yardage bonuses are not projected.

**Points share** baseline: `implied points x points_share`, with its own tuned half-life.

## Blend

```
blend = w x opportunity + (1 - w) x Sleeper
```

`w` is picked per position on a 0.05 grid to minimize MAE on earlier seasons. Live weights
come from all seasons 2018-2025 with availability renormalization (`model_card.json`):

| Position | w on our model |
|---|---|
| QB | 0.60 |
| TE | 0.40 |
| WR | 0.35 |
| RB | 0.15 |

When only one projection exists (a rookie with no NFL game, a K or DEF), that one is used.

## Tuned parameters (current model card)

| Parameter | Value | Grid searched |
|---|---|---|
| `hl_share` | 2 games | 1, 1.5, 2, 3, 4, 6, 8, 12 |
| `hl_eff` | 3 games | 1, 2, 3, 4, 6, 8, 16, 32 |
| `k_mult` | 0.5 | 0.125, 0.25, 0.5, 1, 2 |
| `hl_team` | 8 games | 2, 4, 8, 16, 32 |
| points-share half-life | 8 games | same as `hl_share` |
| `beta_target` (midweek) | 0.5 | 0, 0.25, 0.5, 0.75, 1 |
| `beta_carry` (midweek) | 0.75 | same |
| `beta_att` (midweek) | 0.75 | same |

The betas were tuned on 2016-2018 (roster status is complete from 2016). The `lock` version
tuned to 0.5, 0.5, 0.75.

See `docs/backtest.md` for how they were chosen and how much each matters.

## Not modeled yet
- Questionable players are treated as playing, with no discount.
- Who absorbs vacated usage beyond "same position group, in proportion to current shares"
  (for example, the WR2 moving into the WR1's role specifically).
- Rookies or new signings with no NFL game absorb usage in reality but are not in S.
- Score distributions (only expected points).
- Kickers and defenses (Sleeper only).
- Opponent defense strength, weather, home field beyond what the lines already price in.
