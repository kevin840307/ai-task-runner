Read-only adversarial challenge. Do not modify project files and do not implement fixes.
{{ instructions }}
Try to disprove completeness using only concrete current-project evidence. Focus on material omissions, contradictions, ambiguous expectations, unsupported assumptions, and missing boundary/error behavior.
PASS when no concrete material weakness remains; otherwise return actionable gaps.
Return only JSON:
{"completed":true|false,"reason":"...","missing_items":[]}
