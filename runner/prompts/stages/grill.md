Read-only Grill. Do not modify project files or implement fixes.
{{ always_instructions }}

Goal:
{{ goal }}

Task:
{% if task %}{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}{% else %}Verify the current completed implementation for the goal above.{% endif %}

Challenge the current implementation against the goal and task using current project evidence when needed.
FAIL only for concrete blocking issues that must be fixed before continuing.
Do not invent problems or fail for optional improvements.
If no concrete blocking issue exists, PASS.

{% include "stages/review_output_contract.md" %}
