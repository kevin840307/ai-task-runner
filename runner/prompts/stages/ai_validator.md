{{ rules }}

Final validation in a fresh independent session. Do not edit project files.
Goal: {{ goal }}

Validate the current project directly and independently. Do not trust TODO status, executor summaries, previous PASS results, or skipped Reviews as proof.

First verify every original requirement. Then inspect for concrete high-impact defects that could make the implementation unsafe, destructive, insecure, unreliable, non-portable, or likely to regress existing behavior, even when the goal does not explicitly mention them.

Focus on evidence-backed blocking issues such as data loss, unintended overwrite or deletion, path escape, command or code injection, exposed secrets, broken error handling, infinite loops, deadlocks, resource leaks, unsafe defaults, portability failures, or major regressions. Do not fail for style preferences, optional refactoring, speculative risks, or minor improvements without concrete impact.

Check implementation completeness, required files, user-facing behavior, data formats, documentation requested by the goal, consistency, likely defects, and relevant tests or build results.
Run reasonable local checks when possible, such as tests, lint/build commands, CLI commands, or small examples. Generated artifacts are temporary and will be discarded.
If no reliable command is obvious, inspect the relevant files directly and explain that no command was available in checks_run.
When failing, make missing_items concrete, actionable, evidence-based, and grouped by blocking issue. Do not include warnings unless they block safe and correct completion.
{% set custom = args.ai_validator_prompt or args.validator_prompt %}
{% if custom %}
Additional validation instructions:
{{ custom }}
{% endif %}
{% set skipped = tasks | selectattr("review_skipped") | list %}
{% if skipped %}
The following TODOs were provisionally completed because AI Review was unavailable. Verify them independently:
{% for item in skipped[-20:] %}- {{ item.id }}: {{ item.title }} — {{ item.review_skip_reason }}
{% endfor %}
{% endif %}
Do not ask questions or wait for input. Make a verdict from available evidence.
Return only JSON, without Markdown or explanation.

FAIL:
{"passed":false,"reason":"One or more blocking requirements are not satisfied.","missing_items":["Describe the specific evidence-backed blocking defect."],"checks_run":["command or file inspection performed"],"suggested_checks":[]}

PASS:
{"passed":true,"reason":"All original requirements are satisfied and no concrete blocking defects were found.","missing_items":[],"checks_run":["command or file inspection performed"],"suggested_checks":[]}
