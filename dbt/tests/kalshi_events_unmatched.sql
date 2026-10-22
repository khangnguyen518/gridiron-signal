-- Warns on recorded Kalshi games that match no nflverse game (a team code or date mismatch).
-- Games beyond the loaded schedule also land here until sports_db loads them.
{{ config(severity='warn') }}
select distinct l.event, l.event_date, l.away, l.home
from {{ source('nflm_raw', 'kalshi_game_lines') }} as l
left join (select distinct event from {{ ref('int_kalshi_game_lines') }}) as m
    on l.event = m.event
where m.event is null
