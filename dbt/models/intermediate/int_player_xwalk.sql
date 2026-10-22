-- Sleeper player_id to nflverse gsis_id, from nflverse weekly rosters.
-- A Sleeper ID that maps to more than one gsis_id is dropped, never guessed.
with pairs as (
    select distinct
        nullif(trim(cast(sleeper_id as string)), '') as sleeper_id,
        nullif(trim(cast(gsis_id as string)), '') as gsis_id
    from {{ source('sports_db_raw', 'rosters_weekly') }}
    where position in ('QB', 'RB', 'WR', 'TE')
),

clean as (
    select sleeper_id, gsis_id
    from pairs
    where sleeper_id is not null and gsis_id is not null
    qualify count(*) over (partition by sleeper_id) = 1
)

select sleeper_id, gsis_id
from clean
qualify count(*) over (partition by gsis_id) = 1
