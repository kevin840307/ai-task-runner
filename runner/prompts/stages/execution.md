{{ rules }}

Goal (global constraints only):
{{ goal }}

The Current TODO is the only executable scope.

Execution:
- Understand the TODO, inspect only the needed existing implementation, and reuse established code paths/conventions.
- Work from the smallest relevant scope. For large or multi-project systems, trace only callers, dependencies, contracts, and project boundaries required by this TODO; expand only from evidence.
- If internally complex, execute it incrementally: make one coherent sub-change, verify an important intermediate result when useful, then continue. Do not create Runner TODOs.
- Make the smallest maintainable change satisfying the deliverable and acceptance criteria. Do not work on later TODOs or unrelated cleanup/refactoring.
- If evidence disproves the approach, adjust it. Report a genuine blocker instead of guessing. Once enough evidence exists to execute or decide, stop exploring.

Evidence and testing:
- Use the cheapest validation that provides adequate evidence: focused existing check/test, then targeted regression/command, then relevant module/package suite; use broader validation only when the change or risk requires it.
- Add or update focused tests when they materially protect a reproducible bug, important behavior, new path, or regression-prone edge case.
- Do not repeatedly run expensive broad validation after small edits or run the final project validator unless this TODO requires it.
- Stop when concrete evidence proves the acceptance criteria. Treat Review/Validator failures as evidence. Diagnose the root cause and preserve correct work.
- Validator files may be read for expected behavior but never modified, bypassed, weakened, replaced, or hardcoded against. Do not alter expected/reference/golden/snapshot/fixture data merely to force PASS unless the Goal intentionally changes it.

Safety:
- After a tool error, change action, target, or arguments; do not immediately repeat the identical failed action without new evidence.
- Use only tools needed for this TODO; do not start unrelated/background work or leave unnecessary scratch/diagnostic files.

Context:
{{ {"cycle": workflow.cycle, "validator_feedback": workflow.validator_feedback[-2000:]} | tojson }}
{% if validation.validator_path %}Validator: {{ validation.validator_path }}
{% endif %}
Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
{% if task.last_output %}Previous attempt:
{{ task.last_output[-2000:] }}
{% endif %}
{% if task.last_review and task.last_review.completed is sameas false %}Latest review:
{{ {"reason": task.last_review.reason, "missing_items": task.last_review.missing_items} | tojson }}
{% endif %}
{% if (task.last_review and task.last_review.completed is sameas false) or validation.feedback %}Repair only concrete Review/Validator gaps; preserve correct existing work.
{% endif %}
Return a factual summary of changed files, behavior implemented, and focused checks/tests actually run.
