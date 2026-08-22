$rules

Original goal (context and global constraints only; never executable scope):
$goal

Current TODO is the only executable scope. Use the original goal only to clarify this TODO and its global constraints; never use it to discover or perform later work.
Before writing, inspect only the project files directly needed for this TODO. If required information is still missing after bounded inspection, report the blocker instead of expanding into another TODO.
Make the smallest maintainable change that satisfies the deliverable and acceptance criteria. If no project change is required, do not modify files.
Run only focused checks needed for this TODO. Do not run the final project validator or broad end-to-end validation unless this TODO explicitly requires it. After a plausible fix, run the smallest focused verification that can prove the current acceptance criteria; if it passes, stop immediately instead of continuing exploration. Treat that PASS as sufficient evidence; do not reopen already-proven work or seek extra confirmation unless new contradictory evidence appears.
Treat validator feedback as authoritative for reported failures; fix the first blocking error before other work. Read only the smallest relevant report subset and do not repeatedly reread the same report.
You may read validator files to understand expected behavior, but never modify them or hardcode validator internals.
Expected/reference/golden/snapshot/fixture files are read-only unless the user explicitly requested changing the expected result. Fix the implementation instead of the fixture.
After any tool error, change the next action or arguments; never immediately repeat the identical tool call. Do not repeat the same inspection or test hypothesis without new evidence. Stop when the TODO is satisfied or safely improved; do not continue exploring or work on later TODOs.
Do not ask questions or wait for input. Make the safest reasonable assumption within the current TODO.
Work directly in this session; do not delegate to subagents or use computer-use, browser, desktop, app-launch, background, or scaffolding tools.
Do not leave scratch, diagnostic, runner-state, sidecar, or ad hoc verification files in the project unless they are required deliverables. Use an existing temporary location for disposable checks and remove any temporary artifacts before finishing.

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
