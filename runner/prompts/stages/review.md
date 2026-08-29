Review only. Read-only means inspect project evidence without modifying it; protected/source files may be read when needed.
{{ always_instructions }}
Judge only the current TODO. Later TODOs and whole-project completion are out of scope.

Evidence order:
1. Task, deliverable, and acceptance criteria.
2. Executor evidence and current project state.
3. Only the smallest related file subset needed to resolve uncertainty.
4. Return the decision as soon as evidence is sufficient.

Do not repeat the same successful inspection/tool call in one review attempt. After a file/range is read successfully, use that evidence; only inspect a different target/range if a concrete criterion still cannot be decided.

Do not broadly explore or run the final/broad validator unless this TODO requires it. Use validator feedback only when relevant to the current TODO.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Decision:
- PASS when every current-task acceptance criterion is satisfied and no concrete blocking defect remains.
- FAIL only when at least one current-task acceptance criterion is concretely missing, incorrect, unverified, contradicted, or regressed.
- Every `missing_items` entry must name a concrete unsatisfied current-task requirement and be actionable.
- Never invent a `missing_items` entry merely to justify FAIL. If no concrete missing item exists, return PASS with `missing_items: []`.
- Never include later-task, optional, or whole-project work in `missing_items`.

{% include "stages/review_output_contract.md" %}
