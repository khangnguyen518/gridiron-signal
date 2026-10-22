-- Every recorded Kalshi line snapshot, matched to its nflverse game.
-- Kalshi names a game by its Eastern date and away+home codes; nflverse uses LA and JAX where
-- Kalshi uses LAR and JAC. Only snapshots taken before kickoff are pregame information.
with lines as (
    select *
    from {{ source('nflm_raw', 'kalshi_game_lines') }}
    -- one row per event per snapshot, even if a snapshot was ever loaded twice
    qualify row_number() over (partition by event, snapshot_at order by snapshot_at) = 1
),

games as (
    select
        game_id,
        season,
        week,
        kickoff_utc,
        date(kickoff_utc, 'America/New_York') as game_date_et,
        team as home_team,
        opponent as away_team,
        case team when 'LA' then 'LAR' when 'JAX' then 'JAC' else team end as home_kalshi,
        case opponent when 'LA' then 'LAR' when 'JAX' then 'JAC' else opponent end as away_kalshi,
        spread as nflverse_home_spread,
        total_line as nflverse_total
    from {{ ref('int_team_games') }}
    where is_home
)

select
    g.game_id,
    g.season,
    g.week,
    g.kickoff_utc,
    g.home_team,
    g.away_team,
    l.event,
    l.snapshot_at,
    timestamp_diff(g.kickoff_utc, l.snapshot_at, minute) / 60 as hours_to_kickoff,
    l.snapshot_at < g.kickoff_utc as is_pregame,
    l.home_spread,
    l.total,
    l.home_win_prob,
    (l.total + l.home_spread) / 2 as home_implied_points,
    (l.total - l.home_spread) / 2 as away_implied_points,
    l.spread_markets,
    l.total_markets,
    g.nflverse_home_spread,
    g.nflverse_total
from lines as l
inner join games as g
    on l.away = g.away_kalshi
    and l.home = g.home_kalshi
    and l.event_date = g.game_date_et
