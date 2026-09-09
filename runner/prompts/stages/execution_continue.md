Continue the CURRENT TODO in this same execution session. The Goal and execution rules already remain in context; do not restart discovery or repeat unchanged work.
{% if (task.last_review and task.last_review.completed is sameas false) or validation.feedback %}
Repair only the remaining concrete gaps from the new evidence below. Preserve correct work and fix shared root causes before stacking local patches. Add/update a focused regression test only when it materially protects the repaired behavior.
{% if task.last_review and task.last_review.completed is sameas false %}Latest review:
{{ {"reason": task.last_review.reason, "missing_items": task.last_review.missing_items} | tojson }}
{% endif %}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
{% else %}
New Current TODO:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Inspect only the additional local context needed for this TODO and continue with executable progress.
{% endif %}
Return a factual summary of changed files, behavior implemented, and focused checks/tests actually run.
