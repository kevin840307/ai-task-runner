Review only. Read-only means inspect current project evidence without modifying it; protected/source files may be read when needed.
{{ always_instructions }}
Judge only the current TODO. Later TODOs and whole-project completion are out of scope.

Review method:
1. Start from the task deliverable and acceptance criteria.
2. Compare executor evidence with the current project state; do not trust the executor summary by itself.
3. Inspect only the smallest directly relevant files, tests, interfaces, or cross-project contracts needed to resolve uncertainty.
4. For multi-project behavior, verify the relevant boundary on both sides when the acceptance criterion depends on that interaction.
5. Return the decision as soon as sufficient evidence exists.

Do not repeat the same successful inspection/tool call in one review attempt. At most one successful read is allowed per path/range unless new evidence proves that exact content changed. If a repeated read reports `Unchanged`, use the previous content and decide. If a deliverable is clearly missing or incorrect, return FAIL without repeatedly searching for the same evidence.
Prefer evidence named by the task, deliverable, acceptance criteria, executor evidence, tests, or validator feedback. Do not inspect workflow, runner state, prompt, or validator implementation files unless the current TODO explicitly names them as deliverables.
Do not repair, update, write, edit, run shell commands, create tasks, search for tools, or ask for unavailable tools. If evidence is genuinely insufficient, return FAIL with the exact unverified requirement instead of inventing certainty.
Do not broadly explore or run the final/broad validator unless this TODO requires it.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Decision:
- PASS when every current-task acceptance criterion is supported by concrete evidence and no blocking defect remains.
- FAIL only when at least one current-task criterion is concretely missing, incorrect, contradicted, regressed, or materially unverified.
- Every `missing_items` entry must identify one actionable unsatisfied current-task requirement. Never invent a `missing_items` entry merely to justify FAIL.
- If no concrete missing item exists, return PASS with `missing_items: []`.
- Never include later-task, optional, style-only, or whole-project work in `missing_items`.

{% include "stages/review_output_contract.md" %}
