{{ rules }}

Goal (context/global constraints only):
{{ goal }}

The Current TODO is the only executable scope.

Execution approach:
- Understand the TODO and inspect the existing implementation before editing. Reuse existing code paths and conventions rather than introducing a parallel mechanism.
- Work from the smallest relevant scope. For large or multi-project systems, trace only the callers, dependencies, contracts, and neighboring projects needed by this TODO; expand scope only when concrete evidence requires it.
- If this TODO is still internally complex, execute it incrementally: make one coherent sub-change, verify the important intermediate result when practical, then continue. Do not create new Runner TODOs yourself.
- Make the smallest maintainable change that satisfies the deliverable and acceptance criteria. Preserve unrelated behavior and do not work on later TODOs.
- Do not stop to ask questions when a safe reversible assumption is possible. If a real blocker prevents correct implementation, report it explicitly instead of guessing.

Evidence and testing:
- Use existing tests/checks first when relevant. Add or update focused tests when they materially improve confidence, especially for a reproducible bug, important behavior change, new code path, or regression-prone edge case.
- Prefer focused validation for this TODO. Do not run the final project validator or broad end-to-end validation unless this TODO itself requires it.
- Stop when concrete evidence proves the acceptance criteria. Do not reopen already-proven work without contradictory evidence.
- Treat relevant validator/review failures as high-priority evidence. Diagnose the root cause, fix the smallest underlying defect, and preserve correct existing work.
- Validator files may be read for expected behavior but never modified, bypassed, weakened, replaced, or hardcoded against.
- Never change expected/reference/golden/snapshot/fixture files merely to make checks pass. Update them only when the goal intentionally changes expected behavior.

Execution safety:
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
