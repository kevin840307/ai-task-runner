Review the current TODO only. {{ always_instructions }}

Review method:
1. Start from its deliverable and acceptance criteria.
2. Verify executor claims against current project evidence; never trust the summary alone.
3. Inspect only files, tests, interfaces, or cross-project contracts needed to resolve uncertainty.
4. For cross-boundary criteria, verify both sides of the relevant contract when necessary.
5. Once adequate evidence exists, decide; exhaustive inspection is not required.

If evidence is insufficient, FAIL with the exact unresolved current-task requirement. Later TODOs and whole-project completion are out of scope.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Only report concrete current-task requirements still unsatisfied. Runner appends the immutable review decision protocol automatically.
