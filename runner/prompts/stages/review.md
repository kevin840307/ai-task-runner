Review the current TODO only. {{ always_instructions }}

Review method:
1. Start from its deliverable and acceptance criteria.
2. Start with the executor's concrete changed-file/check evidence and the acceptance criteria. Reuse it when it is specific and internally consistent, but verify any material claim whose correctness is still uncertain.
3. Inspect only the smallest files, tests, interfaces, or cross-project contracts needed to resolve a specific uncertainty. Do not perform a fresh broad code review when the acceptance criteria can already be decided from focused evidence.
4. For cross-boundary criteria, verify both sides of the relevant contract when necessary.
5. Check implementation shape only where it affects maintainability: prefer the smallest coherent solution, with clear ownership and no ad-hoc patch chain or unnecessary abstraction. Treat concrete architecture/maintenance regressions as blocking, not stylistic preferences.
6. Once adequate evidence exists for every acceptance criterion, decide immediately; exhaustive inspection and optional improvement hunting are not required.

If evidence is insufficient, FAIL with the exact unresolved current-task requirement. Later TODOs and whole-project completion are out of scope.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Only report concrete current-task requirements still unsatisfied. Runner appends the immutable review decision protocol automatically.

Efficiency rule: PASS promptly when all current-TODO acceptance criteria have concrete evidence. FAIL only for an actual unsatisfied criterion or a material evidence gap that must be resolved before the TODO can safely proceed.
