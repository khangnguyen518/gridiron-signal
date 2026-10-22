-- Model input: one row per skill player per regular-season game played,
-- with the team's lines and volume, and Sleeper's projection and league-scored
-- actual for the benchmark (null before 2018 or when the player is unmatched).
select
    p.*,
    x.sleeper_id,
    tg.is_home,
    tg.spread,
    tg.total_line,
    tg.implied_points,
    tg.lines_known_at,
    tg.points_scored as team_points,
    tg.pass_attempts as team_pass_attempts,
    tg.sacks as team_sacks,
    tg.rush_attempts as team_rush_attempts,
    tg.pass_tds as team_pass_tds,
    tg.rush_tds as team_rush_tds,
    tg.rz_pass_attempts as team_rz_pass_attempts,
    tg.rz_rush_attempts as team_rz_rush_attempts,
    sp.league_id,
    sp.projected_points as sleeper_projected_points,
    sa.actual_points as sleeper_actual_points
from {{ ref('int_player_games') }} as p
inner join {{ ref('int_team_games') }} as tg
    on p.game_id = tg.game_id and p.team = tg.team
left join {{ ref('int_player_xwalk') }} as x
    on p.gsis_id = x.gsis_id
left join {{ source('ff', 'int_weekly_projected_points') }} as sp
    on x.sleeper_id = sp.player_id and p.season = sp.season and p.week = sp.week
left join {{ source('ff', 'int_weekly_actual_points') }} as sa
    on x.sleeper_id = sa.player_id and p.season = sa.season and p.week = sa.week
        and sa.league_id = sp.league_id
