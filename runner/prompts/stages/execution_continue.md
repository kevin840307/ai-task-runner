Continue normal task execution in this same session. The execution rules and Goal already remain in context; do not restart or re-read unrelated work.
{% if stage == "repair" %}
Repair the current TODO using only the new Review/Validator evidence below. Preserve correct existing work.
{% if task.last_review and task.last_review.completed is sameas false %}Latest review:
{{ {"reason": task.last_review.reason, "missing_items": task.last_review.missing_items} | tojson }}
{% endif %}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
{% else %}
New Current TODO:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
{% endif %}
Return a factual summary of changed files and focused checks.
