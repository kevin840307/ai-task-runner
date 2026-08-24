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

For repair planning, address only unresolved validator gaps, keep the original goal authoritative, and group failures that share one root cause.
Create the minimum number of coherent implementation TODOs needed. Each TODO must produce one observable result, be independently executable/reviewable, and contain only task-specific acceptance criteria.
Do not create inspection-only, review-only, validator-only, preparation, or umbrella TODOs unless the goal explicitly requires that deliverable.

{% include "stages/plan_output_contract.md" %}
