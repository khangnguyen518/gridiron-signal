-- One row per team per regular-season game: closing lines from the team's side,
-- points scored, and offensive volume. Lines are known 5 minutes before kickoff
-- (sports_db lines_known_at); everything else is an outcome.
with games as (
    select *
    from {{ source('sports_db', 'stg_nflverse__schedules') }}
    where game_type = 'REG' and season >= {{ var('first_season') }}
),

sides as (
    select
        game_id, season, week, kickoff_utc, lines_known_at,
        home_team as team, away_team as opponent, true as is_home,
        spread_line as spread, total_line, home_score as points_scored, home_coach as head_coach
    from games
    union all
    select
        game_id, season, week, kickoff_utc, lines_known_at,
        away_team, home_team, false,
        -spread_line, total_line, away_score, away_coach
    from games
),

team_stats as (
    select
        game_id,
        team,
        attempts as pass_attempts,
        sacks_suffered as sacks,
        carries as rush_attempts,
        passing_tds as pass_tds,
        rushing_tds as rush_tds
    from {{ source('sports_db', 'stg_nflverse__team_stats_week') }}
    where season_type = 'REG' and season >= {{ var('first_season') }}
),

red_zone as (
    select
        game_id,
        {{ team_code_asof('posteam', 'season') }} as team,
        countif(pass_attempt = 1 and sack = 0) as rz_pass_attempts,
        countif(rush_attempt = 1) as rz_rush_attempts
    from {{ source('sports_db', 'stg_nflverse__pbp') }}
    where season >= {{ var('first_season') }}
        and season_type = 'REG'
        and yardline_100 <= 20
        and coalesce(two_point_attempt, 0) = 0
    group by 1, 2
)

select
    s.game_id,
    s.season,
    s.week,
    s.kickoff_utc,
    s.lines_known_at,
    s.team,
    s.opponent,
    s.is_home,
    s.head_coach,
    -- spread from this team's side: positive means favored (nflverse spread_line is home margin)
    s.spread,
    s.total_line,
    (s.total_line + s.spread) / 2 as implied_points,
    s.points_scored,
    ts.pass_attempts,
    ts.sacks,
    ts.rush_attempts,
    ts.pass_tds,
    ts.rush_tds,
    coalesce(rz.rz_pass_attempts, 0) as rz_pass_attempts,
    coalesce(rz.rz_rush_attempts, 0) as rz_rush_attempts
from sides as s
left join team_stats as ts on s.game_id = ts.game_id and s.team = ts.team
left join red_zone as rz on s.game_id = rz.game_id and s.team = rz.team
