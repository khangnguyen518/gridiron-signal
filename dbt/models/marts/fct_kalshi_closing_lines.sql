-- Kalshi's last pregame line per game, next to nflverse's closing line.
-- The closing spread and total come from the last snapshot before kickoff that had a full ladder;
-- the win probability from the last pregame snapshot that had one.
with pregame as (
    select *
    from {{ ref('int_kalshi_game_lines') }}
    where is_pregame
),

ladders as (
    select *
    from pregame
    where home_spread is not null and total is not null
    qualify row_number() over (partition by game_id order by snapshot_at desc) = 1
),

win_prob as (
    select game_id, home_win_prob, snapshot_at as win_prob_at
    from pregame
    where home_win_prob is not null
    qualify row_number() over (partition by game_id order by snapshot_at desc) = 1
),

coverage as (
    select
        game_id,
        any_value(season) as season,
        any_value(week) as week,
        any_value(kickoff_utc) as kickoff_utc,
        any_value(home_team) as home_team,
        any_value(away_team) as away_team,
        any_value(nflverse_home_spread) as nflverse_home_spread,
        any_value(nflverse_total) as nflverse_total,
        count(*) as pregame_snapshots,
        min(snapshot_at) as first_snapshot_at
    from pregame
    group by 1
)

select
    c.game_id,
    c.season,
    c.week,
    c.kickoff_utc,
    c.home_team,
    c.away_team,
    l.snapshot_at as closing_snapshot_at,
    l.hours_to_kickoff as closing_hours_to_kickoff,
    l.home_spread as kalshi_home_spread,
    l.total as kalshi_total,
    l.home_implied_points,
    l.away_implied_points,
    w.home_win_prob as kalshi_home_win_prob,
    w.win_prob_at,
    c.nflverse_home_spread,
    c.nflverse_total,
    l.home_spread - c.nflverse_home_spread as spread_diff,
    l.total - c.nflverse_total as total_diff,
    c.pregame_snapshots,
    c.first_snapshot_at
from coverage as c
left join ladders as l on c.game_id = l.game_id
left join win_prob as w on c.game_id = w.game_id
