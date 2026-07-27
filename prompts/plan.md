$planning_rules

Plan only the remaining work for this goal:
$goal

Project root to inspect:
$root

Project files:
$outline

Progress:
$progress_json

Use the project outline and progress above for planning; do not read files during planning.
Choose task count from actual complexity; there is no limit.
If the goal lists numbered or bulleted deliverables, usually create one ordered task per deliverable.
If the goal is a dense paragraph, first identify deliverables before choosing task count.
If the goal implies multiple deliverables such as source files, CLI behavior, generated outputs, tests, validators, persistence, data formats, or documentation, split them into ordered tasks.
Right-size the task list: trivial goals can be one task, small tools usually need a few deliverable-sized tasks, and broad goals need more tasks grouped by verifiable outcomes.
Do not collapse a broad or multi-file goal into one "build everything" task.
Do not create tasks for pure constraints or instructions such as not asking questions, keeping code small, or verifying work; put those into acceptance criteria instead.
Each task must be ordered, independently executable, meaningful, and have clear acceptance criteria.
Avoid unrelated work in one task and tiny mechanical steps.
If planning notes are written, they may be JSON or Markdown files only under this runner work directory: $work_dir
Prefer returning the final tasks JSON directly instead of writing files during planning.
Do not create, edit, delete, or rename project implementation files during planning; implementation happens only after tasks are returned.
Do not use Qwen todo tools during planning; Python owns task order and completion state.
Do not implement, ask questions, or wait for input. Make reasonable assumptions from the project.
Return at least one task. Never return an empty tasks array.

Return only this JSON shape, without Markdown or explanation:
{"tasks":[{"title":"Implement requested change","description":"Make the smallest maintainable project change needed to satisfy the goal.","acceptance_criteria":["The requested behavior is implemented","Relevant checks pass"]}]}
