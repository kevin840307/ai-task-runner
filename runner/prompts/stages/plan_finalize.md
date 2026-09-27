{% include "stages/planning_rules.md" %}
{{ always_instructions }}

Create the implementation plan now. Use read-only inspection only when available evidence is insufficient; do not inspect files merely because tools are available.

Goal:
{{ goal }}

Project root: {{ project.root }}
Progress:
{{ planning.progress | tojson }}
{% if planning.inspection_summary %}Relevant prior evidence:
{{ planning.inspection_summary }}
{% endif %}

Produce the minimum executable TODO set that can complete the Goal from the CURRENT project state. Preserve valid existing work. When Progress contains validator or replan feedback, address only unresolved Goal requirements and do not create a separate repair phase.

Runner appends the immutable plan/TODO contract automatically.
