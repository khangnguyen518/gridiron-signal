-- Fails on any line that was not public before kickoff.
{% test lines_before_kickoff(model, column_name) %}
select *
from {{ model }}
where {{ column_name }} >= kickoff_utc
{% endtest %}
