$planning_rules

Plan only the remaining work for this goal:
$goal

Project root to inspect:
$root

Project files:
$outline

Progress:
$progress_json
$planning_feedback

Use the project outline and progress above for planning; do not read files during planning.
Always return valid JSON even if the goal is ambiguous or the project outline is incomplete.
When uncertain, choose the smallest conservative task list that can still complete the goal.
If the project already has code or the architecture is unclear, include an early read-only survey TODO so implementation tasks can follow the existing structure.
Choose task count from actual complexity; there is no fixed limit.
First identify concrete deliverables from the goal, then split by verifiable output families: files, commands, data contracts, generated outputs, reports, docs, or user-facing behavior.
If the goal lists numbered or bulleted deliverables, usually create one ordered task per deliverable; for dense paragraphs, split by deliverable nouns and verifiable outcomes.
Right-size the task list: trivial goals can be one task, small tools usually need 2-5 deliverable-sized tasks, and broad or multi-file goals often need 6-20 tasks grouped by verifiable outcomes.
Do not collapse a broad or multi-file goal into one "build everything" task.
Prefer tasks that produce or modify a coherent deliverable. Do not create separate tasks for rules, examples, expected output descriptions, merge-order steps, or validation criteria unless they require a distinct file or user-facing output.
Do not create tasks for pure constraints or instructions such as not asking questions, keeping code small, avoiding hardcode, or verifying work; put those into acceptance criteria instead.
Each task must be ordered, independently executable, meaningful, and have clear acceptance criteria describing completion evidence.
Include this acceptance criterion in every task: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.
If planning notes are written, they may be JSON or Markdown files only under this runner work directory: $work_dir
Prefer returning the final tasks JSON directly instead of writing files during planning.
Do not create, edit, delete, or rename project implementation files during planning; implementation happens only after tasks are returned.
Do not use Qwen todo tools during planning; Python owns task order and completion state.
Do not implement, ask questions, or wait for input. Make reasonable assumptions from the project.
Return at least one task. Never return an empty tasks array.
Before answering, self-check that the JSON parses and that every task has title, description, and acceptance_criteria.

Return only this JSON shape, without Markdown or explanation:
{"tasks":[{"title":"Implement requested change","description":"Make the smallest maintainable project change needed to satisfy the goal.","acceptance_criteria":["The requested behavior is implemented","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior","Relevant checks pass"]}]}
