$rules

Execute only the current task below. Do not start later tasks.
Use this order: inspect relevant project files, make the smallest maintainable change, run focused local checks, then fix the first failure if any.
If Run context includes validator_feedback, treat it as authoritative and fix the reported problem before doing other work.
If validator_feedback mentions `Full report`, `report_dir`, or a `.ai-task-runner/validator-reports/` path, read the referenced report files before editing.
Create only files that are required by the task or clearly useful for validation.
Do not create scripts, commands, or files whose purpose is to update runner state, task status, reviews, attempts, or `.ai-task-runner`; only implement the requested project behavior.
Prefer file edit/write tools for creating or changing files. Use shell commands mainly for checks, tests, and small local scripts.
Do not delegate to subagents, background agents, scaffolding skills, or app-generation skills. Complete the current task directly in this session.
Do not use computer-use, desktop, browser, or app-launch tools; this runner works through project files and shell checks.
If a required file or command is missing, create or fix it instead of repeating the same read/check command. Do not call the same tool repeatedly with identical arguments after it returns the same result.
You may read validator files to understand expected behavior, but never modify them or hardcode validator internals. Python runs the final validator after review; use validator feedback and the validator reference only to guide the project implementation.
Do not ask questions or wait for input. Resolve ambiguity with the safest reasonable assumption and continue.

Run context:
$context_json
$validator_reference

Task:
$task_json
$previous
$strategy
Finish with a factual summary of changed files and checks.
