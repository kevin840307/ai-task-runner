Re-review the CURRENT result for the same TODO in this same read-only review session. The full review rules and JSON contract already remain in context.
Re-read the new executor evidence and the minimum directly related project evidence needed; do not reuse the previous verdict when the artifact has changed.
New executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
Only report concrete unsatisfied requirements for this TODO. Do not repeat a previous missing item if it is now satisfied, and do not invent one to force FAIL. If no concrete missing item remains, return PASS with `missing_items: []`.
Return only one valid review JSON decision using the original contract.
