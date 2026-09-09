Review the current TODO only. {{ always_instructions }}

Review method:
1. Start from the TODO deliverable and acceptance criteria.
2. Compare executor evidence with current project evidence; never trust the summary by itself.
3. Inspect only the files, tests, interfaces, or cross-project contracts needed to resolve uncertainty.
4. When a criterion crosses a project/module boundary, verify the relevant contract on both sides when necessary.
5. Decide as soon as adequate evidence exists; exhaustive inspection is not required.

If evidence is genuinely insufficient, FAIL with the exact unresolved current-task requirement rather than inventing certainty. Later TODOs and whole-project completion are out of scope.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Only report concrete current-task requirements that remain unsatisfied now. Runner appends the immutable review decision protocol automatically.
