-- Sleeper's weekly projection and league-scored actual for kickers and team defenses, the
-- benchmark for decision 0021. A defense's Sleeper ID is its team code (LAR for nflverse's LA);
-- a kicker's comes from int_player_xwalk.
with kickers as (
    select x.sleeper_id, x.gsis_id
    from {{ ref('int_player_xwalk') }} as x
    inner join (
        select distinct gsis_id from {{ ref('int_kicker_games') }}
    ) as k using (gsis_id)
),

ids as (
    select player_id, season, week, league_id, projected_points
    from {{ source('ff', 'int_weekly_projected_points') }}
),

actuals as (
    select player_id, season, week, league_id, actual_points
    from {{ source('ff', 'int_weekly_actual_points') }}
),

both_sides as (
    select
        coalesce(p.player_id, a.player_id) as sleeper_id,
        coalesce(p.season, a.season) as season,
        coalesce(p.week, a.week) as week,
        coalesce(p.league_id, a.league_id) as league_id,
        p.projected_points,
        a.actual_points
    from ids as p
    full outer join actuals as a
        on p.player_id = a.player_id and p.season = a.season and p.week = a.week and p.league_id = a.league_id
)

select
    b.sleeper_id,
    b.season,
    b.week,
    b.league_id,
    if(k.gsis_id is null, 'DEF', 'K') as position,
    k.gsis_id,
    if(k.gsis_id is null, if(b.sleeper_id = 'LAR', 'LA', b.sleeper_id), null) as team,
    b.projected_points,
    b.actual_points
from both_sides as b
left join kickers as k
    on b.sleeper_id = k.sleeper_id
where k.gsis_id is not null
    or regexp_contains(b.sleeper_id, r'^[A-Z]{2,3}$')
