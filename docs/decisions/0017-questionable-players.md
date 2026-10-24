# 0017. Questionable players: chance to play and production when playing

- Status: Accepted
- Date: 2026-10-24
- Amends: 0009

## Context
0009 treats Questionable players as playing at full projection, and the backtest scores only
games a player played, so the cost of starting someone who sits is never measured. On regulars
(players who played their team's previous game), the last practice before the game separates
them sharply:

| Questionable, last practice | Played, 2016-2018 | Played, 2019-2025 |
|---|---|---|
| Did not participate | 44.6% (130) | 44.9% (350) |
| Limited | 73.0% (529) | 70.6% (1,107) |
| Full | 87.9% (165) | 79.1% (234) |

Healthy regulars played 86.8% of 2019-2025 games. Questionable players who did play scored
less than the blend projected relative to healthy players (actual / blend 0.88 after no practice,
1.00 limited, 1.05 full, against 1.09 healthy). Outside work agrees: about 71% of final-report
Questionable players play (Footballguys, 2017-2023), and they score about 18% below their healthy
average (4for4).

## Decision
- `int_player_game_status` carries the last practice status known before kickoff and the
  player's Sleeper projection, so the backtest can score expected-to-play players who sat.
- The backtest adds an `expected` row set: every player expected to play under the midweek
  rule with a Sleeper projection, scored 0 when he did not play. Existing row sets stay
  played-only, so earlier results remain comparable.
- For a Questionable player, projection = blend x P(play | practice) x m(practice), where
  P(play) and m (production when playing, relative to healthy players) are fit on 2016-2018
  regulars, the availability tuning seasons. Other players are unchanged.
- Live, practice status comes from sports_db's nflverse injury report (Sleeper's practice field
  is empty). Simulated games give a Questionable player 0 points at the rate 1 - P(play).

## Why
- Fit on 2016-2018 regulars: P(play) 0.445 after no practice, 0.727 limited, 0.873 full; production
  when playing 0.84, 0.93 and 0.94 of a healthy player's against the same projection.
- Backtest `20261024_110340`, 2019-2025, every expected player with those who sat scored 0
  (52,840 rows, 13,555 sat), week-bootstrap 95% intervals, adjusted minus unadjusted:

| | Our model | Blend |
|---|---|---|
| MAE, Questionable players | -0.94 (-1.04 to -0.83) | -0.91 (-1.01 to -0.80) |
| MAE, projected 5 or more | -0.075 (-0.086 to -0.064) | -0.081 (-0.093 to -0.069) |
| MAE, all expected players | -0.050 (-0.055 to -0.044) | -0.049 (-0.056 to -0.043) |
| Start/sit pairs with one Questionable player | +8.4 pts (+7.1 to +9.7) | +9.9 pts (+8.7 to +11.1) |

- The table carries over: on 2019-2025 Questionable players averaged 3.25 points after no
  practice (adjusted projection 2.99), 5.47 limited (5.57) and 5.73 full (5.53).
- Sleeper's stored projections cannot score players who sat: they exist for 96% of Questionable
  regulars who played and 15% of those who sat, so they were updated after inactives. The blend
  test uses each player's Sleeper projection from his latest earlier week, for every row alike.
- Live, Sleeper does not discount Questionable players (Sleeper / ours 1.01 for them against
  0.86 for healthy players, week 7 of 2026), so the multiplier is not counted twice.

## Consequences
- A Questionable player's shown projection is his expected points, so one who did not practice
  drops to about 0.37 of his full projection. Check inactives 90 minutes before kickoff: once
  he is confirmed active, his full projection applies.
- The played-only row sets and the blend weights are unchanged; the adjustment is applied after
  the blend and is measured only on the `expected` rows (`questionable.csv`).
- Teammates do not yet absorb a Questionable player's expected missing share: renormalization
  still counts him as fully playing. That is a separate step.
