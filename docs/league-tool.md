# League tool

`nflm league` connects a Sleeper league and answers three questions for one week:
who to start, which starts are close calls, and who to pick up.

## Usage

```bash
uv run nflm league                                  # league and user from .env, Sleeper's current week
uv run nflm league --week 8
uv run nflm league --league-id 1234567890 --user "display name"
uv run nflm league --refresh                        # re-read BigQuery after a dbt build
```

Without a user, the command lists every team's display name and stops. Set
`SLEEPER_USERNAME` in `.env` to skip `--user`. All Sleeper reads are public; no login.

## What it prints

**Matchup.** Your win probability against this week's opponent, with both teams' median and
80% range of total points. The opponent's lineup is the starters they have set in Sleeper, or their
best-projection lineup if none are set. If swapping bench players raises win probability, the swaps
are listed with the new win probability (saved as `lineup_max_win.csv`).

**Best lineup.** Your roster placed into the league's slots to maximize total projection.
Columns: slot, player, role (WR1, RB2, ... from this week's depth chart and recent usage; plain
position for kickers, defenses and players with no history), team, opponent, `proj` (what the
lineup uses), `p10` and `p90`
(the 80% range: one game in ten lands below p10, one above p90), `ours`, `sleeper`, the team's
implied points, and a flag.

**Bench.** Everyone else on your roster, same columns.

**Close calls.** Bench players projected within 2 points of a starter whose slot they can
fill, with your win probability as is and if swapped. The higher projection wins these only
about 55% of the time, so win probability is the better tiebreaker: when you are the underdog,
the player with more upside can be the better start even with a lower projection.

**Waiver targets.** The best 8 unrostered players per position this week, sorted by
`upgrade`: their projection minus the weakest starter they could replace in your lineup.
Also shows recent target and carry share and Sleeper's 24-hour add count.

How ranges and win probability are computed: `docs/model.md`, "Game simulation and ranges".
How well the ranges are calibrated: `docs/backtest.md`, "Ranges".

CSV copies of each table, plus every player's projections, go to
`output/league/<league>_<season>_w<week>_<time>/`.

## How `proj` is set

| Situation | `proj` |
|---|---|
| Both projections exist | `w x ours + (1 - w) x Sleeper + shift`, w and the median shift per position from the model card (decision 0016) |

The shown projection is the shifted blend, a median. Lineup ranking, the expected total, ranges and
win probabilities use the blend before the shift, a mean: a lineup's total sums means, and the
shift differs by position, so ranking on medians would tilt FLEX picks (decision 0016).
| Rookie with no NFL game yet | Sleeper only (flag "no history: Sleeper only") |
| Kicker or defense | Sleeper only |
| Injury status Out, IR, PUP, Sus, NA or DNR | 0, flagged with the status |
| Team on bye | 0, flagged "bye" |
| Questionable | unchanged, flagged |
| Doubtful | unchanged, flagged; counted as not playing when renormalizing teammates |

**Teammates of absent players.** Before projecting, each team's usage shares are renormalized
over the players Sleeper does not list as Out, IR, PUP, Sus, NA, DNR or Doubtful: RB, WR and TE
target shares and RB carry shares move toward the team's usual total for that position, and a
backup QB takes over the starter's attempts when the starter is out. See `docs/model.md`,
"Availability renormalization". Check Sleeper's injury status close to kickoff: a late change
moves teammates' projections.

Both projections are scored with **your league's** `scoring_settings`. TE, RB and WR reception
bonuses are applied by position. Yardage bonuses are not.

## Lines

For each of the week's games the tool reads Kalshi's open markets:
- `KXNFLTOTAL`: "Over X points" at many strikes. The mid price is P(total > X).
- `KXNFLSPREAD`: "TEAM wins by over X" for each team. The home team's markets give
  P(home margin > X); the away team's give P(home margin < -X).

The line is where that probability crosses 50%, by linear interpolation between strikes
(`lines.ladder_median`). Markets with no bid or no ask are skipped. Games Kalshi does not list
keep sports_db's latest nflverse line. The first note printed says how many games came from each.

Team codes differ: Kalshi uses `LAR` and `JAC` where nflverse uses `LA` and `JAX`.

## Lineup rules

Slots come from the league's `roster_positions`, minus BN, IR and TAXI.

| Slot | Eligible |
|---|---|
| QB, RB, WR, TE, K, DEF | that position |
| FLEX | RB, WR, TE |
| WRRB_FLEX | RB, WR |
| REC_FLEX | WR, TE |
| SUPER_FLEX | QB, RB, WR, TE |

Slots are filled most restrictive first, each with the best eligible player left. For these
nested slot types that order gives the best total.

## Notes printed before the tables

- **Lines:** how many games used Kalshi vs nflverse.
- **Stats end at week N:** sports_db's stats lag the week being projected. Usage from later
  weeks is missing, which matters most for rookies and changing roles. Follow `docs/runbook.md`.

## Limits
- Kicker and defense ranges are assumed Normal spreads, not backtested, and independent of their games.
- Win probability assumes the opponent's lineup stays as set; it does not anticipate their changes.
- Questionable players are not discounted, and their teammates are not adjusted for them.
- Blend weights were fit on full PPR. Other scoring still gets exact points.
- Sleeper's current team decides where a player plays; a trade shows up as soon as Sleeper updates.
