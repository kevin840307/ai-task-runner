{{ rules }}

Final validation. This is a fresh independent read-only session.
Goal: {{ goal }}

Verify the current project directly against every original requirement. Do not treat TODO status, executor summaries, prior PASS results, or skipped Reviews as proof.
Check completeness, required files, user-visible behavior, data formats, requested documentation, consistency, and relevant tests/build results.
Also check evidence-backed blocking defects in destructive file/data behavior, security/injection/secrets, failure/concurrency/resource handling, portability, or major regressions.
Do not fail for style preferences, optional refactoring, speculative risks, or non-blocking improvements.

Run reasonable focused checks when useful. If no reliable command is obvious, inspect the relevant files and record that in `checks_run`.
On FAIL, make `missing_items` concrete, actionable, evidence-based, and limited to blocking issues.
{% if validation.instructions %}Additional validation instructions:
{{ validation.instructions }}
{% endif %}
{% if instructions %}Workflow validation instructions:
{{ instructions }}
{% endif %}
{% set skipped = tasks | selectattr("review_skipped") | list %}
{% if skipped %}Independently verify these TODOs because Review was unavailable:
{% for item in skipped[-20:] %}- {{ item.id }}: {{ item.title }} — {{ item.review_skip_reason }}
{% endfor %}
{% endif %}
Return only JSON. Do not ask questions.

FAIL:
{"passed":false,"reason":"One or more blocking requirements are not satisfied.","missing_items":["Specific evidence-backed blocking defect."],"checks_run":["command or file inspection performed"],"suggested_checks":[]}

PASS:
{"passed":true,"reason":"All original requirements are satisfied and no concrete blocking defects were found.","missing_items":[],"checks_run":["command or file inspection performed"],"suggested_checks":[]}
