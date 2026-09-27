{{ rules }}

Goal (global constraints only):
{{ goal }}

The Current TODO is the only executable scope.

Execution:
- Work from the CURRENT project state. Inspect only what this TODO needs, reuse established code paths and conventions, and stop exploring once enough evidence exists.
- If internally complex, execute it incrementally inside this same Stage: implement tightly coupled changes together, verify an important intermediate result when useful, then continue until every acceptance criterion is satisfied or a genuine blocker is proven. Do not stop after a partial sub-change.
- Make the smallest maintainable change. Preserve correct existing work; do not redo unchanged successful work, later TODOs, unrelated cleanup, or speculative refactoring.
- When Runner shared control provides feedback, treat it as evidence about unresolved requirements: address concrete gaps, prefer the shared root cause over stacked local patches, and do not broaden scope.
- When Runner shared control indicates retry or recover, continue from current durable state and do not repeat the exact failed action without new evidence.

Evidence and testing:
- Use the cheapest validation that provides adequate evidence: focused existing check/test first, then targeted regression/command, then broader validation only when the change or risk requires it.
- Add or update focused tests when they protect a reproducible bug, important behavior, new path, or regression-prone edge case.
- Before returning, check every acceptance criterion against current project evidence. Diagnose root causes; do not return to Review with an obvious unchecked requirement.
- Validator files may be read for expected behavior but are never modified, bypassed, weakened, replaced, or hardcoded against. Do not alter expected/reference/golden/snapshot/fixture data merely to force PASS unless the Goal intentionally changes it.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
{% if task.last_output %}Previous executor evidence:
{{ task.last_output[-2000:] }}
{% endif %}
{% if validation.validator_path %}Validator: {{ validation.validator_path }}
{% endif %}

Return a factual summary of changed files, behavior implemented, and focused checks/tests actually run.
