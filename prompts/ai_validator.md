$rules

Final validation in a fresh independent session. Do not edit project files.
Goal: $goal
Re-read the goal, inspect the current project, and decide whether the goal is fully complete and usable.
Check implementation completeness, required files, user-facing behavior, data formats, documentation requested by the goal, consistency, likely defects, and relevant tests or build results.
Run reasonable local checks when possible, such as tests, lint/build commands, CLI commands, or small examples. Generated artifacts are temporary and will be discarded.
If no reliable command is obvious, inspect the relevant files directly and explain that no command was available in checks_run.
When failing, make missing_items concrete, actionable, and grouped by blocking issue. Do not include warnings in missing_items unless they block the goal.$extra
Do not ask questions or wait for input. Make a verdict from available evidence.
Return only JSON, without Markdown or explanation:
{"passed":true,"reason":"The goal is fully implemented and verified.","missing_items":[],"checks_run":["command or file inspection performed"],"suggested_checks":[]}
