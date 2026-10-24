-- One row per skill player on a team's weekly roster per regular-season game: whether he was
-- expected to play, from information public before kickoff, and whether he did.
--   expected_active_lock:    on the game-day active list (status ACT) and not reported Out.
--                            The inactive list is public about 90 minutes before kickoff.
--   expected_active_midweek: on the roster (ACT or INA) and not reported Out or Doubtful.
--                            Uses only the injury report, as a lineup set midweek would.
-- The injury status is the last version known before kickoff (sports_db injuries history), with
-- that report's last practice participation (DNP, Limited, Full) for Questionable modeling (0017).
-- Sleeper's projection is joined so the backtest can score expected players who sat.
with rosters as (
    select season, week, team, gsis_id, position, full_name, status as roster_status
    from {{ source('sports_db', 'stg_nflverse__rosters_weekly') }}
    where game_type = 'REG'
        and season >= {{ var('first_season') }}
        and position in ('QB', 'RB', 'WR', 'TE')
        and gsis_id is not null
        and status in ('ACT', 'INA', 'RES', 'PUP', 'SUS')
    qualify row_number() over (partition by season, week, gsis_id order by known_at desc) = 1
),

injuries as (
    select
        season,
        week,
        gsis_id,
        report_status,
        case
            when practice_status like 'Did Not%' then 'DNP'
            when practice_status like 'Limited%' then 'Limited'
            when practice_status like 'Full%' then 'Full'
        end as practice_status
    from {{ source('sports_db', 'stg_nflverse__injuries_history') }}
    where game_type = 'REG'
        and season >= {{ var('first_season') }}
        and known_at < kickoff_utc
    qualify row_number() over (partition by season, week, gsis_id order by known_at desc) = 1
),

games as (
    select game_id, season, week, team, kickoff_utc
    from {{ ref('int_team_games') }}
),

played as (
    select game_id, gsis_id
    from {{ ref('int_player_games') }}
),

depth as (
    select game_id, gsis_id, depth_position, depth_tier, depth_rank
    from {{ ref('int_player_game_depth') }}
),

sleeper as (
    select x.gsis_id, sp.season, sp.week, sp.projected_points
    from {{ ref('int_player_xwalk') }} as x
    inner join {{ source('ff', 'int_weekly_projected_points') }} as sp
        on x.sleeper_id = sp.player_id
)

select
    g.game_id,
    g.season,
    g.week,
    g.kickoff_utc,
    r.team,
    r.gsis_id,
    r.full_name as player_name,
    r.position,
    r.roster_status,
    i.report_status as injury_status,
    i.practice_status,
    r.roster_status = 'ACT' and coalesce(i.report_status, '') != 'Out' as expected_active_lock,
    r.roster_status in ('ACT', 'INA')
        and coalesce(i.report_status, '') not in ('Out', 'Doubtful') as expected_active_midweek,
    p.gsis_id is not null as played,
    dc.depth_position,
    dc.depth_tier,
    dc.depth_rank,
    sl.projected_points as sleeper_projected_points
from rosters as r
inner join games as g
    on r.season = g.season and r.week = g.week and r.team = g.team
left join injuries as i
    on r.season = i.season and r.week = i.week and r.gsis_id = i.gsis_id
left join played as p
    on g.game_id = p.game_id and r.gsis_id = p.gsis_id
left join depth as dc
    on g.game_id = dc.game_id and r.gsis_id = dc.gsis_id
left join sleeper as sl
    on r.gsis_id = sl.gsis_id and r.season = sl.season and r.week = sl.week
