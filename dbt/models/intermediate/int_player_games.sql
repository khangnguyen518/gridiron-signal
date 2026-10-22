-- One row per skill player per regular-season game played: the box score the
-- projection model uses, plus red-zone opportunities from play-by-play.
with stats as (
    select *
    from {{ source('sports_db', 'stg_nflverse__player_stats_week') }}
    where season_type = 'REG'
        and season >= {{ var('first_season') }}
        and not is_team_row
        and position in ('QB', 'RB', 'WR', 'TE')
),

pbp as (
    select game_id, receiver_player_id, rusher_player_id, pass_attempt, rush_attempt, sack
    from {{ source('sports_db', 'stg_nflverse__pbp') }}
    where season >= {{ var('first_season') }}
        and season_type = 'REG'
        and yardline_100 <= 20
        and coalesce(two_point_attempt, 0) = 0
),

rz_targets as (
    select game_id, receiver_player_id as gsis_id, count(*) as rz_targets
    from pbp
    where pass_attempt = 1 and sack = 0 and receiver_player_id is not null
    group by 1, 2
),

rz_carries as (
    select game_id, rusher_player_id as gsis_id, count(*) as rz_carries
    from pbp
    where rush_attempt = 1 and rusher_player_id is not null
    group by 1, 2
)

select
    s.game_id,
    s.season,
    s.week,
    s.kickoff_utc,
    s.gsis_id,
    s.player_display_name as player_name,
    s.position,
    s.team,
    s.opponent_team as opponent,

    coalesce(s.attempts, 0) as pass_attempts,
    coalesce(s.completions, 0) as completions,
    coalesce(s.passing_yards, 0) as pass_yards,
    coalesce(s.passing_tds, 0) as pass_tds,
    coalesce(s.passing_interceptions, 0) as interceptions,
    coalesce(s.passing_2pt_conversions, 0) as pass_2pt,

    coalesce(s.carries, 0) as carries,
    coalesce(s.rushing_yards, 0) as rush_yards,
    coalesce(s.rushing_tds, 0) as rush_tds,
    coalesce(s.rushing_2pt_conversions, 0) as rush_2pt,

    coalesce(s.targets, 0) as targets,
    coalesce(s.receptions, 0) as receptions,
    coalesce(s.receiving_yards, 0) as rec_yards,
    coalesce(s.receiving_tds, 0) as rec_tds,
    coalesce(s.receiving_2pt_conversions, 0) as rec_2pt,
    coalesce(s.receiving_air_yards, 0) as air_yards,

    coalesce(s.rushing_fumbles_lost, 0)
        + coalesce(s.receiving_fumbles_lost, 0)
        + coalesce(s.sack_fumbles_lost, 0) as fumbles_lost,

    coalesce(t.rz_targets, 0) as rz_targets,
    coalesce(c.rz_carries, 0) as rz_carries
from stats as s
left join rz_targets as t on s.game_id = t.game_id and s.gsis_id = t.gsis_id
left join rz_carries as c on s.game_id = c.game_id and s.gsis_id = c.gsis_id
