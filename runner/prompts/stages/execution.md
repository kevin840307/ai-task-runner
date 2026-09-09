{{ rules }}

Goal (context/global constraints only):
{{ goal }}

The Current TODO is the only executable scope.

Execution:
- Understand the TODO and inspect the existing implementation before editing. Reuse existing code paths and conventions rather than creating a parallel mechanism.
- Work from the smallest relevant scope. For large or multi-project systems, trace only the callers, dependencies, contracts, and neighboring project boundaries required by this TODO; expand only from concrete evidence.
- If the TODO is internally complex, execute it incrementally: complete one coherent sub-change, verify an important intermediate result when useful, then continue. Do not create new Runner TODOs yourself.
- Make the smallest maintainable change that satisfies the deliverable and acceptance criteria. Do not work on later TODOs or perform unrelated cleanup/refactoring unless it blocks this TODO.
- If new evidence invalidates the current approach, adjust the implementation rather than continuing a known-wrong path. Report a genuine blocker instead of guessing.

Evidence and testing:
- Use the cheapest validation that provides adequate evidence: existing focused test/check first, then a focused regression test or targeted command, then a relevant module/package suite, and broader validation only when the change or risk requires it.
- Add or update focused tests when they materially improve confidence, especially for a reproducible bug, important behavior change, new path, or regression-prone edge case.
- Do not repeatedly run expensive broad validation after every small sub-change. Do not run the final project validator unless this TODO itself requires it.
- Stop when concrete evidence proves the acceptance criteria. Do not reopen already-proven work without contradictory evidence.
- Treat relevant validator/review failures as high-priority evidence. Diagnose the root cause, fix the smallest underlying defect, and preserve correct existing work.
- Validator files may be read for expected behavior but never modified, bypassed, weakened, replaced, or hardcoded against. Never change expected/reference/golden/snapshot/fixture files merely to make checks pass unless the goal intentionally changes that expected behavior.

Safety:
- After a tool error, change the action, target, or arguments; never immediately repeat an identical failed action without new evidence.
- Use only tools needed for this TODO. Do not delegate or start unrelated/background work.
- Do not leave scratch, diagnostic, Runner-state, sidecar, or ad hoc verification files unless they are required deliverables.

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
{% if (task.last_review and task.last_review.completed is sameas false) or validation.feedback %}Repair only the concrete Review/Validator gaps; preserve correct existing work.
{% endif %}
Return a factual summary of changed files, behavior implemented, and focused checks/tests actually run.
