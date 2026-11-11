-- One row per team defense (DEF) per regular-season game played: its fantasy stat line, in
-- Sleeper's definitions (decision 0021). Checked against Sleeper's league-scored DEF actuals for
-- 2018-2025: rebuilt points match exactly in 82% of team-games and within 2 points in 95.5%
-- (mean difference 0.36; the rest are minor special-teams stats).
--   pts_allowed: the opponent's points minus 6 for each of its defensive or special-teams
--                touchdowns (Sleeper scores points allowed by the defense, not the team).
--   def_td:      defensive and special-teams touchdowns (interception, fumble, kick returns).
with plays as (
    select
        game_id,
        {{ team_code_asof('posteam', 'season') }} as posteam,
        {{ team_code_asof('defteam', 'season') }} as defteam,
        {{ team_code_asof('td_team', 'season') }} as td_team,
        {{ team_code_asof('fumble_recovery_1_team', 'season') }} as fumble_recovery_team,
        coalesce(special_teams_play, 0) = 1
            or play_type in ('kickoff', 'punt', 'field_goal', 'extra_point') as is_st,
        coalesce(sack, 0) = 1 as is_sack,
        coalesce(interception, 0) = 1 as is_int,
        coalesce(fumble_lost, 0) = 1 as is_fumble_lost,
        coalesce(fumble_forced, 0) = 1 as is_ff,
        coalesce(touchdown, 0) = 1 as is_td,
        coalesce(safety, 0) = 1 as is_safety,
        coalesce(punt_blocked, 0) = 1
            or field_goal_result = 'blocked'
            or extra_point_result = 'blocked' as is_blocked_kick
    from {{ source('sports_db', 'stg_nflverse__pbp') }}
    where season >= {{ var('first_season') }}
        and season_type = 'REG'
        and defteam is not null
),

by_defense as (
    select
        game_id,
        defteam as team,
        countif(is_sack and not is_st) as sacks,
        countif(is_int) as ints,
        countif(is_fumble_lost and not is_st and fumble_recovery_team = defteam) as fum_rec,
        countif(is_ff and not is_st) as ff,
        countif(is_td and td_team = defteam) as def_td,
        countif(is_safety) as safeties,
        countif(is_blocked_kick) as blk_kick,
        countif(is_fumble_lost and is_st and fumble_recovery_team = defteam) as st_fum_rec
    from plays
    group by 1, 2
),

games as (
    select game_id, season, week, kickoff_utc, team, opponent
    from {{ ref('int_team_games') }}
    where points_scored is not null
),

opponent_points as (
    select game_id, team as opponent, points_scored as opp_points
    from {{ ref('int_team_games') }}
)

select
    g.game_id,
    g.season,
    g.week,
    g.kickoff_utc,
    g.team,
    g.opponent,
    o.opp_points,
    o.opp_points - 6 * coalesce(od.def_td, 0) as pts_allowed,
    coalesce(d.sacks, 0) as sacks,
    coalesce(d.ints, 0) as ints,
    coalesce(d.fum_rec, 0) as fum_rec,
    coalesce(d.ff, 0) as ff,
    coalesce(d.def_td, 0) as def_td,
    coalesce(d.safeties, 0) as safeties,
    coalesce(d.blk_kick, 0) as blk_kick,
    coalesce(d.st_fum_rec, 0) as st_fum_rec
from games as g
inner join opponent_points as o
    on g.game_id = o.game_id and g.opponent = o.opponent
left join by_defense as d
    on g.game_id = d.game_id and g.team = d.team
left join by_defense as od
    on g.game_id = od.game_id and g.opponent = od.team
