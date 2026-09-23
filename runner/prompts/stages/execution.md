{{ rules }}

Goal (global constraints only):
{{ goal }}

The Current TODO is the only executable scope.

Execution:
- Inspect only what this TODO needs and reuse established code paths/conventions. For large or multi-project systems, trace only required callers, dependencies, contracts, and boundaries; once enough evidence exists, stop exploring.
- If internally complex, execute it incrementally inside this same session: implement tightly coupled changes together, verify an important intermediate result when useful, then continue until every acceptance criterion is satisfied or a genuine blocker is proven. Do not stop after a partial sub-change.
- Make the smallest maintainable change. Do not work on later TODOs, unrelated cleanup, or speculative refactoring. Preserve correct existing work.
- If evidence disproves the approach, adjust it instead of repeating failed actions.

Evidence and testing:
- Use the cheapest validation that provides adequate evidence: focused existing check/test first, then targeted regression/command, then broader validation only when the change or risk requires it.
- Add or update focused tests when they protect a reproducible bug, important behavior, new path, or regression-prone edge case.
- Before returning, check every acceptance criterion against current project evidence. Diagnose the root cause of failures; do not return to Review with an obvious unchecked requirement.
- Validator files may be read for expected behavior but are never modified, bypassed, weakened, replaced, or hardcoded against. Do not alter expected/reference/golden/snapshot/fixture data merely to force PASS unless the Goal intentionally changes it.

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
