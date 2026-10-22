-- Each skill player's spot on his team's depth chart going into a regular-season game, from charts
-- public before kickoff:
--   2025 onward: the last daily snapshot before kickoff (3WR 1TE grouping). WR ranks run across the
--                three receiver spots (1-3 are the starters), so tier = ceil(rank / 3) for WR and
--                tier = rank for RB, TE and QB.
--   through 2024: the weekly chart, known 24 hours before the week's first kickoff. Tier = depth_team.
--                 About 2.4 WRs share tier 1 each week (X, Z and slot starters).
-- Tier 1 is a starter. Ordering within a tier is left to recent usage (roles.py).
with games as (
    select game_id, season, week, team, kickoff_utc
    from {{ ref('int_team_games') }}
),

old_format as (
    select
        g.game_id,
        d.gsis_id,
        case d.depth_position when 'HB' then 'RB' else d.depth_position end as depth_position,
        min(safe_cast(d.depth_team as int64)) as depth_tier,
        min(safe_cast(d.depth_team as int64)) as depth_rank
    from {{ source('sports_db', 'stg_nflverse__depth_charts_weekly') }} as d
    inner join games as g
        on d.season = g.season and d.week = g.week and d.team = g.team
    where d.game_type = 'REG'
        and d.formation = 'Offense'
        and d.depth_position in ('QB', 'RB', 'HB', 'WR', 'TE')
        and d.gsis_id is not null
        and d.known_at < g.kickoff_utc
    group by 1, 2, 3
),

new_snapshots as (
    select
        g.game_id,
        g.kickoff_utc,
        d.gsis_id,
        d.pos_abb as depth_position,
        d.pos_rank,
        d.snapshot_at,
        max(d.snapshot_at) over (partition by g.game_id, d.team) as last_snapshot_at
    from {{ source('sports_db', 'stg_nflverse__depth_charts_history') }} as d
    inner join games as g
        on d.team = g.team
        and d.snapshot_at < g.kickoff_utc
        and d.snapshot_at >= timestamp_sub(g.kickoff_utc, interval 10 day)
    where d.pos_grp = '3WR 1TE'
        and d.pos_abb in ('QB', 'RB', 'WR', 'TE')
        and d.gsis_id is not null
),

new_format as (
    select
        game_id,
        gsis_id,
        depth_position,
        min(if(depth_position = 'WR', cast(ceil(pos_rank / 3) as int64), pos_rank)) as depth_tier,
        min(pos_rank) as depth_rank
    from new_snapshots
    where snapshot_at = last_snapshot_at
    group by 1, 2, 3
),

combined as (
    select * from old_format
    union all
    select * from new_format
)

-- A player listed at two positions keeps his best (lowest) tier
select game_id, gsis_id, depth_position, depth_tier, depth_rank
from combined
qualify row_number() over (partition by game_id, gsis_id order by depth_tier, depth_rank) = 1
