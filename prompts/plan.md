$planning_rules

Plan only the remaining work for this goal:
$goal

Project root to inspect:
$root

Project files:
$outline

Progress:
$progress_json

If plan_quality_feedback is non-empty, correct that exact structural issue before returning the next plan.
Use the project outline only as a starting point. Inspect relevant project files read-only before planning.
Identify the requested observable outcomes, affected existing behavior, dependencies, interfaces, conventions, and available verification evidence.
Return valid JSON even when information is incomplete. Make the safest reasonable assumptions from the project rather than asking questions.
Choose the smallest complete task list. Task count must follow actual independently implementable and independently verifiable outcomes, with no fixed minimum or maximum.
Treat explicit headings and list items as required coverage, but split or combine only when the inspected project shows that outcomes are independently executable and reviewable.
For unstructured goals, derive tasks from distinct observable outcomes and completion evidence rather than language-specific words, file types, technologies, or formatting guesses.
Keep constraints and quality requirements in the acceptance criteria of the affected tasks instead of creating standalone implementation tasks for them.
Each task must represent one coherent project change or output family and must include objective acceptance criteria.
Split a task when its outcomes can fail, be reviewed, or be validated independently. Do not split into tiny mechanical edits that have no independent completion evidence.
If planning notes are written, they may be JSON or Markdown files only under this runner work directory: $work_dir
Prefer returning the final tasks JSON directly instead of writing files during planning.
Do not create, edit, delete, or rename project implementation files during planning; inspect them read-only and implement only after tasks are returned.
Do not use agent-owned todo tools during planning; Python owns task order and completion state.
Do not implement, ask questions, or wait for input.
Return at least one task. Never return an empty tasks array.
Before answering, verify that every explicit goal item is covered, no tasks are duplicates, no task contains multiple explicitly structured outcomes, and every task has title, description, and acceptance_criteria.

Return only this JSON shape, without Markdown or explanation:
{"tasks":[{"title":"Implement requested change","description":"Make the smallest maintainable project change needed to satisfy the goal.","acceptance_criteria":["The requested behavior is implemented","Relevant checks pass"]}]}
