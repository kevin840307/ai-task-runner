{% include "stages/planning_rules.md" %}
{{ always_instructions }}

Create the {{ planning.mode }} implementation plan now. Do not use more tools.

Goal:
{{ goal }}

Project root: {{ project.root }}
Progress: {{ planning.progress | tojson }}
{% if planning.inspection_summary %}Inspection summary:
{{ planning.inspection_summary }}
{% endif %}

{% include "stages/plan_task_rules.md" %}

{% include "stages/plan_output_contract.md" %}
