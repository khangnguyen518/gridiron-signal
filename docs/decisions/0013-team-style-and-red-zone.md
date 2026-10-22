# 0013. Play calling and red-zone rates for rushing only

- Status: Accepted
- Date: 2026-10-23

## Context
Team volume came from implied points, the spread and the team's recent attempts. Recent attempts
mix a coach's play calling with game script and pace, a new head coach inherited his predecessor's
history, and touchdowns ignored how well a team (and its opponent's defense) finishes drives.

## Decision
- `int_team_game_situations` adds, per team-game from play-by-play: neutral-situation pass rate
  (1st and 2nd down, quarters 1-3, score within 7), plays, red-zone pass rate, red-zone trips and
  touchdowns, and the same allowed by the defense.
- Team features: recency-weighted rates, the opponent's defensive rates on the same row, and the
  play-calling rates shrunk toward team history under a new head coach (pseudo-count 2 games).
- Inputs were chosen per target on 2013-2018 player MAE: rush attempts add the team's neutral pass
  rate, plays per game and the opponent defense's neutral pass rate faced; rush touchdowns add
  red-zone rates. Pass attempts and pass touchdowns keep the lines-only inputs.

## Why
- On 2019-2025 (paired, week-clustered bootstrap): our model's MAE fell 0.0031 (interval -0.0046
  to -0.0017), RBs 0.0110 (-0.0161 to -0.0060); no position got worse. The blend's change, -0.0004,
  is within noise (p = 0.31); its RB gain, -0.0025, is not (p = 0.01).
- Adding the same inputs to passing helped QBs and RBs but made WRs and TEs significantly worse,
  and pass attempts did not improve at the team level on the test seasons.
- Coach shrinkage moved team MAE by under 0.001 on 2019-2025: team history at an 8-game half-life
  already adapts within a few games.

## Consequences
- Play-by-play uses today's codes for relocated teams (LA, LAC, LV) in every season. The macro
  `team_code_asof` maps them; before it, red-zone totals for STL 2010-2015, SD 2010-2016 and OAK
  2010-2019 were zero. A dbt test now fails if any played team-game lacks situation data.
- The live model reads `int_team_game_situations`; the VM's prod dataset needs a refresh after deploy.
