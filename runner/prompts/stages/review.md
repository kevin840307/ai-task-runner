Review only. Read-only: do not modify project files.
{{ always_instructions }}
Judge only the current TODO. Later TODOs and whole-project completion are out of scope.

Evidence order:
1. Task, deliverable, and acceptance criteria.
2. Executor evidence and current project state.
3. Only the smallest related file subset needed to resolve uncertainty.
4. Return the decision as soon as evidence is sufficient.

Do not broadly explore or run the final/broad validator unless this TODO requires it. Use validator feedback only when relevant to the current TODO.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Decision:
- PASS only when every current-task acceptance criterion is satisfied.
- FAIL only for concrete missing, incorrect, unverified, contradicted, or regressed current-task results.
- `missing_items` must be concrete and actionable; never include later-task or whole-project work.
- Never return FAIL with an empty `missing_items`.

{% include "stages/review_output_contract.md" %}
