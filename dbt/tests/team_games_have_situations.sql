-- Fails if a played team-game has no play-by-play situation row: the sign of a team-code
-- mismatch between play-by-play and the schedule (see macros/team_code_asof.sql).
select tg.game_id, tg.team
from {{ ref('int_team_games') }} as tg
left join {{ ref('int_team_game_situations') }} as s
    on tg.game_id = s.game_id and tg.team = s.team
where tg.points_scored is not null and s.team is null
