{#
  nflverse play-by-play uses today's codes for relocated teams in every season; schedules and
  player stats use the code of the time. This maps a play-by-play code to the schedule's.
#}
{% macro team_code_asof(code, season) -%}
    case
        when {{ code }} = 'LA' and {{ season }} <= 2015 then 'STL'
        when {{ code }} = 'LAC' and {{ season }} <= 2016 then 'SD'
        when {{ code }} = 'LV' and {{ season }} <= 2019 then 'OAK'
        else {{ code }}
    end
{%- endmacro %}
