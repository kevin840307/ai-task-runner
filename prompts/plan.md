$planning_rules

Plan only the remaining work for this goal:
$goal

Project root to inspect:
$root

Project files:
$outline

Progress:
$progress_json

Use the project outline as a starting point, then inspect the relevant project files read-only before planning.
Use read, list, glob, and search tools only as needed to understand entry points, dependencies, public interfaces, existing patterns, and relevant tests.
First identify concrete deliverables and their actual affected components, then convert them into tasks.
Always return valid JSON even if the goal is ambiguous or the project outline is incomplete.
When uncertain, choose the smallest complete task list, not the smallest task count.
Choose task count from actual complexity; there is no fixed limit.
Treat numbered or bulleted deliverables as starting points. Split a deliverable further when it contains multiple independently implementable or independently verifiable outcomes.
If the goal is a dense paragraph, split by deliverable nouns and verifiable outcomes before choosing task count.
If the goal implies multiple deliverables such as source files, CLI behavior, generated outputs, tests, validators, persistence, data formats, templates, configuration, or documentation, split them into ordered tasks.
Right-size the task list: trivial goals can be one task, small tools usually need 2-5 deliverable-sized tasks, and broad or multi-file goals often need 6-20 or more tasks grouped by verifiable outcomes.
For each complex case, consider its normal path, error and recovery paths, persistence or external integration, compatibility impact, and focused tests.
Do not collapse a broad or multi-file goal, complex case, or cross-component behavior into one "build everything" task.
Do not create tasks for pure constraints or instructions such as not asking questions, keeping code small, avoiding hardcode, or verifying work; put those into acceptance criteria instead.
Each task must be ordered, independently executable, meaningful, and have clear acceptance criteria.
Prefer deliverable-sized tasks over tiny mechanical steps.
Each task should describe exactly one independently reviewable project change or output family, plus its completion evidence.
If one task would modify unrelated components or require several independent test groups, split it.
If planning notes are written, they may be JSON or Markdown files only under this runner work directory: $work_dir
Prefer returning the final tasks JSON directly instead of writing files during planning.
Do not create, edit, delete, or rename project implementation files during planning; inspect them read-only and implement only after tasks are returned.
Do not use Qwen todo tools during planning; Python owns task order and completion state.
Do not implement, ask questions, or wait for input. Make reasonable assumptions from the project.
Return at least one task. Never return an empty tasks array.
Before answering, self-check requirement coverage, split any task that contains multiple independently testable outcomes, and confirm that the JSON parses and every task has title, description, and acceptance_criteria.

Return only this JSON shape, without Markdown or explanation:
{"tasks":[{"title":"Implement requested change","description":"Make the smallest maintainable project change needed to satisfy the goal.","acceptance_criteria":["The requested behavior is implemented","Relevant checks pass"]}]}
