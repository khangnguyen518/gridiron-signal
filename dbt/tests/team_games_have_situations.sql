-- Fails if a played team-game has no play-by-play situation row: the sign of a team-code
-- mismatch between play-by-play and the schedule (see macros/team_code_asof.sql).
-- Only games that kicked off more than 36 hours before the build count: a game's final score can
-- reach the schedule before its play-by-play reaches sports_db (one Sunday game on 2026-11-09),
-- and a late load is not a mismatch. A real mismatch persists, so it still fails a day later.
select tg.game_id, tg.team
from {{ ref('int_team_games') }} as tg
left join {{ ref('int_team_game_situations') }} as s
    on tg.game_id = s.game_id and tg.team = s.team
where tg.points_scored is not null
    and s.team is null
    and tg.kickoff_utc < timestamp_sub(current_timestamp(), interval 36 hour)
