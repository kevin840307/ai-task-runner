$rules

Complete only the current TODO, but keep the whole goal and validator feedback in mind. Do not start unrelated TODOs unless they are necessary dependencies for the current one.
Use this order: inspect relevant project files, make the smallest maintainable change, run focused local checks, then fix the first failure if any.
If Run context includes validator_feedback, treat it as authoritative and fix the reported problem before doing other work.
Validator stdout is only a compact summary. If validator_feedback mentions `Full report`, `report_dir`, or a `.ai-task-runner/validator-reports/` path, read `summary.txt` first when it exists, then `errors.txt` when it exists, then only the first relevant `Full report` file needed for the first blocking error. Do not repeatedly read the same report file; after reading, make one concrete project change for the first blocking error. Treat warnings as context unless the validator exits non-zero.
Create only files that are required by the task or clearly useful for validation.
Do not create scripts, commands, memory files, scratch notes, or sidecar files whose purpose is to update runner state, task status, reviews, attempts, or `.ai-task-runner`; only implement the requested project behavior.
Prefer file edit/write tools for creating or changing files. Use shell commands mainly for checks, tests, and small local scripts.
Use shell commands that match the current operating system and shell. On Windows, avoid Unix-only options such as `mkdir -p`; use Python or PowerShell-compatible commands instead.
Do not delegate to subagents, background agents, scaffolding skills, or app-generation skills. Complete the current task directly in this session.
Do not use computer-use, desktop, browser, or app-launch tools; this runner works through project files and shell checks.
If a required file or command is missing, create or fix it instead of repeating the same read/check command. Do not call the same tool repeatedly with identical arguments after it returns the same result.
You may read validator files to understand expected behavior, but never modify them or hardcode validator internals. Python runs the final validator after review; use validator feedback and the validator reference only to guide the project implementation.
You may read expected, reference, golden, snapshot, or fixture files to understand the target output, but do not modify them unless the user explicitly requested changing the expected result. If validator feedback says a file is read-only or an answer fixture, restore that file and fix the project implementation instead.
Do not ask questions or wait for input. Resolve ambiguity with the safest reasonable assumption and continue.

Run context:
$context_json
$validator_reference

Task:
$task_json
$previous
$strategy
Finish with a factual summary of changed files and checks.
