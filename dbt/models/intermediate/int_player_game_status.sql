-- One row per skill player on a team's weekly roster per regular-season game: whether he was
-- expected to play, from information public before kickoff, and whether he did.
--   expected_active_lock:    on the game-day active list (status ACT) and not reported Out.
--                            The inactive list is public about 90 minutes before kickoff.
--   expected_active_midweek: on the roster (ACT or INA) and not reported Out or Doubtful.
--                            Uses only the injury report, as a lineup set midweek would.
-- The injury status is the last version known before kickoff (sports_db injuries history).
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
    select season, week, gsis_id, report_status
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
    r.roster_status = 'ACT' and coalesce(i.report_status, '') != 'Out' as expected_active_lock,
    r.roster_status in ('ACT', 'INA')
        and coalesce(i.report_status, '') not in ('Out', 'Doubtful') as expected_active_midweek,
    p.gsis_id is not null as played
from rosters as r
inner join games as g
    on r.season = g.season and r.week = g.week and r.team = g.team
left join injuries as i
    on r.season = i.season and r.week = i.week and r.gsis_id = i.gsis_id
left join played as p
    on g.game_id = p.game_id and r.gsis_id = p.gsis_id
