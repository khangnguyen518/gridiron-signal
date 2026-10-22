-- One row per team per regular-season game played: how the offense called plays and finished in
-- the red zone, and what its defense allowed. Outcomes of that game; the Python feature step only
-- uses earlier games.
--   neutral: 1st or 2nd down, quarters 1-3, score within 7. Pass rate there reflects play calling,
--            not the scoreboard (the usual "early-down neutral" definition).
--   red zone: plays snapped at or inside the opponent's 20; a trip is a drive that reached it.
with plays as (
    select
        game_id,
        {{ team_code_asof('posteam', 'season') }} as posteam,
        {{ team_code_asof('defteam', 'season') }} as defteam,
        fixed_drive,
        coalesce(pass, 0) = 1 as is_pass,
        coalesce(rush, 0) = 1 as is_rush,
        qtr <= 3 and down in (1, 2) and abs(score_differential) <= 7 as is_neutral,
        yardline_100 <= 20 as is_rz,
        coalesce(drive_inside20, 0) = 1 as drive_reached_rz,
        fixed_drive_result = 'Touchdown' as drive_td,
        coalesce(pass_touchdown, 0) = 1 as pass_td,
        coalesce(rush_touchdown, 0) = 1 as rush_td
    from {{ source('sports_db', 'stg_nflverse__pbp') }}
    where season >= {{ var('first_season') }}
        and season_type = 'REG'
        and posteam is not null
        and coalesce(two_point_attempt, 0) = 0
        and coalesce(qb_kneel, 0) = 0
        and coalesce(qb_spike, 0) = 0
        and (coalesce(pass, 0) = 1 or coalesce(rush, 0) = 1)
),

by_side as (
    select
        game_id,
        posteam as team,
        defteam as opponent,
        count(*) as plays,
        countif(is_pass) as pass_plays,
        countif(is_neutral) as neutral_plays,
        countif(is_neutral and is_pass) as neutral_pass_plays,
        countif(is_rz) as rz_plays,
        countif(is_rz and is_pass) as rz_pass_plays,
        count(distinct if(drive_reached_rz, fixed_drive, null)) as rz_trips,
        count(distinct if(drive_reached_rz and drive_td, fixed_drive, null)) as rz_trip_tds,
        countif(is_rz and pass_td) as rz_pass_tds,
        countif(is_rz and rush_td) as rz_rush_tds
    from plays
    group by 1, 2, 3
)

select
    o.game_id,
    o.team,
    o.plays as off_plays,
    o.pass_plays as off_pass_plays,
    o.neutral_plays as off_neutral_plays,
    o.neutral_pass_plays as off_neutral_pass_plays,
    o.rz_plays as off_rz_plays,
    o.rz_pass_plays as off_rz_pass_plays,
    o.rz_trips as off_rz_trips,
    o.rz_trip_tds as off_rz_trip_tds,
    o.rz_pass_tds as off_rz_pass_tds,
    o.rz_rush_tds as off_rz_rush_tds,
    d.plays as def_plays,
    d.neutral_plays as def_neutral_plays,
    d.neutral_pass_plays as def_neutral_pass_plays,
    d.rz_trips as def_rz_trips,
    d.rz_trip_tds as def_rz_trip_tds,
    d.rz_pass_tds as def_rz_pass_tds,
    d.rz_rush_tds as def_rz_rush_tds
from by_side as o
left join by_side as d
    on o.game_id = d.game_id and o.team = d.opponent
