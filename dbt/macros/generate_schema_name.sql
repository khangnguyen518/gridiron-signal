-- Every model lands in the target dataset. No custom-schema prefixes.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ target.dataset }}
{%- endmacro %}
