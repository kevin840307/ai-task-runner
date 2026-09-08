Continue the CURRENT TODO in this same execution session. The Goal and execution rules already remain in context; do not restart discovery or re-read unrelated work.
{% if (task.last_review and task.last_review.completed is sameas false) or validation.feedback %}
Use the new Review/Validator evidence below to repair only the remaining concrete gaps. Preserve all already-correct work, diagnose shared root causes before making repeated local patches, and add/update a focused regression test when that materially protects the repaired behavior.
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
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
{% endif %}
Return a factual summary of changed files, behavior implemented, and focused checks/tests actually run.
