{{ rules }}

Goal (context/global constraints only):
{{ goal }}

Current TODO is the only executable scope.

Scope:
- Inspect only files directly needed for this TODO. If bounded inspection is insufficient, report the blocker.
- Make the smallest maintainable change that satisfies the deliverable and acceptance criteria. Preserve unrelated behavior.
- Do not work on later TODOs. Do not ask questions; make the safest reasonable assumption from available evidence.

Evidence and validation:
- Run only focused checks needed for this TODO. Do not run the final project validator or broad end-to-end validation unless this TODO requires it.
- Stop when focused evidence proves the acceptance criteria; do not reopen proven work without contradictory evidence.
- Treat concrete validator failures relevant to this TODO as high-priority evidence. Fix the first blocking issue and inspect only the needed report subset.
- Validator files may be read for expected behavior but never modified or hardcoded against.
- Never change expected/reference/golden/snapshot/fixture files merely to make checks pass. Update them only when the goal intentionally changes expected behavior.

Execution safety:
- After a tool error, change the action or arguments; never immediately repeat the identical failed action.
- Use only tools needed for this TODO. Do not delegate or start unrelated/background work.
- Do not leave scratch, diagnostic, Runner-state, sidecar, or ad hoc verification files in the project unless they are required deliverables.

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
{% if stage == "repair" %}Repair only the concrete Review/Validator gaps; preserve correct existing work.
{% endif %}
Return a factual summary of changed files and focused checks.
