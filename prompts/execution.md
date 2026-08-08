$rules

Original goal (context and global constraints only; never executable scope):
$goal

Complete only the current TODO. The current TODO is the only executable scope. Global constraints are boundaries only; they are not additional executable work.
Before every write, confirm that the change is required by the current TODO deliverable or acceptance criteria. If the current deliverable does not require a project change, do not modify project files.
Do not begin, implement, create, modify, or verify work assigned to another TODO, even when it appears to be a dependency, is obvious from the goal, or would make later work easier.
Before changing anything, inspect only the existing project files directly relevant to the current TODO so you understand the current structure, conventions, dependencies, and behavior. This inspection is preparation inside the TODO and never completes the TODO by itself.
If the current TODO still lacks required information after that bounded inspection, stop expanding the inspection. Do not use the original goal or planning output to discover or execute additional work. The original goal above is only for clarifying requirements and global constraints of the current TODO. If it cannot be completed without expanding scope, report the blocker instead of performing another TODO.
Use this order: inspect relevant project files, make the smallest maintainable change, run focused local checks, then fix the first failure if any.
Make concrete progress rather than trying to perfect the entire TODO in one model call. If the whole TODO cannot be safely completed in this call, leave the project in a coherent improved state and return; the runner may continue the same TODO in another attempt.
Do not keep exploring after useful progress has been made. Do not leave temporary, diagnostic, exploratory, scratch, or throwaway project files unless they are required deliverables.
If Run context includes validator_feedback, treat it as authoritative and fix the reported problem before doing other work.
Validator stdout is only a compact summary. If validator_feedback mentions `Full report`, `report_dir`, or a `.ai-task-runner/validator-reports/` path, read `summary.txt` first when it exists, then `errors.txt` when it exists, then only the first relevant `Full report` file needed for the first blocking error. Do not repeatedly read the same report file; after reading, make one concrete project change for the first blocking error. Treat warnings as context unless the validator exits non-zero.
Create only files that are required by the current task. Do not create or modify deliverables assigned to later TODOs.
Use only focused checks needed to prove the current TODO. Do not run the final project validator or broad end-to-end validation unless the current TODO explicitly requires it.
When the current deliverable and acceptance criteria are satisfied, stop immediately and return the summary; do not continue exploring, testing, or improving later work.
Do not create scripts, commands, memory files, scratch notes, or sidecar files whose purpose is to update runner state, task status, reviews, attempts, or `.ai-task-runner`; only implement the requested project behavior.
Prefer file edit/write tools for creating or changing files. Use shell commands mainly for checks, tests, and small local scripts.
Use shell commands that match the current operating system and shell. On Windows, avoid Unix-only options such as `mkdir -p`; use Python or PowerShell-compatible commands instead.
Do not delegate to subagents, background agents, scaffolding skills, or app-generation skills. Complete the current task directly in this session.
Do not use computer-use, desktop, browser, or app-launch tools; this runner works through project files and shell checks.
If a required file or command is missing, create or fix it instead of repeating the same read/check command. After any tool error, change the next action or arguments based on that error; never immediately repeat the identical tool call.
You may read validator files to understand expected behavior, but never modify them or hardcode validator internals. Python runs the final validator after review; use validator feedback and the validator reference only to guide the project implementation.
You may read expected, reference, golden, snapshot, or fixture files to understand the target output, but do not modify them unless the user explicitly requested changing the expected result. If validator feedback says a file is read-only or an answer fixture, restore that file and fix the project implementation instead.
Do not ask questions or wait for input. Resolve ambiguity with the safest reasonable assumption and continue.

Run context:
$context_json
$validator_reference

Task:
$task_json
$previous
$review_feedback
$rebuilt_session_note
$strategy
Finish with a factual summary of changed files and checks.
