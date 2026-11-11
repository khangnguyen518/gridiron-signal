-- One row per kicker per regular-season game he kicked in: field goal attempts and makes by
-- distance band, and extra points (decision 0021). Distance bands are Sleeper's. Rebuilt league
-- points match Sleeper's league-scored K actuals exactly in 99.4% of 2018-2025 kicker-games.
with kicks as (
    select
        game_id,
        {{ team_code_asof('posteam', 'season') }} as team,
        kicker_player_id as gsis_id,
        coalesce(field_goal_attempt, 0) = 1 as is_fga,
        field_goal_result = 'made' as is_fgm,
        kick_distance,
        coalesce(extra_point_attempt, 0) = 1 as is_xpa,
        extra_point_result = 'good' as is_xpm
    from {{ source('sports_db', 'stg_nflverse__pbp') }}
    where season >= {{ var('first_season') }}
        and season_type = 'REG'
        and kicker_player_id is not null
        and (coalesce(field_goal_attempt, 0) = 1 or coalesce(extra_point_attempt, 0) = 1)
)

select
    k.game_id,
    g.season,
    g.week,
    g.kickoff_utc,
    k.team,
    g.opponent,
    k.gsis_id,
    countif(is_fga and kick_distance <= 19) as fga_0_19,
    countif(is_fga and kick_distance between 20 and 29) as fga_20_29,
    countif(is_fga and kick_distance between 30 and 39) as fga_30_39,
    countif(is_fga and kick_distance between 40 and 49) as fga_40_49,
    countif(is_fga and kick_distance >= 50) as fga_50p,
    countif(is_fgm and kick_distance <= 19) as fgm_0_19,
    countif(is_fgm and kick_distance between 20 and 29) as fgm_20_29,
    countif(is_fgm and kick_distance between 30 and 39) as fgm_30_39,
    countif(is_fgm and kick_distance between 40 and 49) as fgm_40_49,
    countif(is_fgm and kick_distance >= 50) as fgm_50p,
    countif(is_fga and not is_fgm) as fgmiss,
    countif(is_xpa) as xpa,
    countif(is_xpm) as xpm,
    countif(is_xpa and not is_xpm) as xpmiss
from kicks as k
inner join {{ ref('int_team_games') }} as g
    on k.game_id = g.game_id and k.team = g.team
group by 1, 2, 3, 4, 5, 6, 7
