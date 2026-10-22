# 0009. Renormalize usage shares by who is expected to play

- Status: Accepted
- Date: 2026-10-21

## Context
Recent usage shares ignore who else plays this week. Before this change the opportunity model
under-projected teammates of a freshly absent starter by about 1 point, and a backup QB kept
his mop-up share when he started. That is information Sleeper also has, but it is where a
model can react faster.

## Decision
- `int_player_game_status` marks each rostered player as expected to play from information
  public before kickoff: `lock` (game-day active list, not Out) and `midweek` (roster, not Out
  or Doubtful).
- For each team-game, RB, WR and TE target shares and RB carry shares are scaled so the players
  expected to play reach the team's own recent total for that position group (times a
  stale-share factor). QB attempt shares are scaled by the top QB's share, not a sum.
- Strength (beta) is tuned per share type on 2016-2018. The live model uses the `midweek`
  settings and Sleeper's injury status.

## Why
- Opportunity MAE 4.726 to 4.662 on 2019-2025; blend 4.535 to 4.525, beating Sleeper in
  6 of 7 seasons instead of 4. On teams with a fresh key absence, our model alone matches
  Sleeper and the blend beats it by 1.3%.
- Each design choice beat its alternative on the tuning seasons: position groups over all
  positions, top QB share over summed QB shares, team-specific totals over league medians
  (see `docs/backtest.md`, "Things tried and dropped").
- 2016-2018 is never scored, and roster status is incomplete before 2016.

## Consequences
- Placeholder rows for rostered players who did not play roughly double the feature table
  (137k rows). `lagged_wsum` takes a `step` mask so those rows never change anyone's history.
- Questionable players count as playing. A late scratch is only caught once Sleeper marks him Out.
- Players with no NFL game (rookies, new signings) are not in S, so their usage is partly
  credited to teammates. Partial beta (0.5 to 0.75) absorbs some of this.
