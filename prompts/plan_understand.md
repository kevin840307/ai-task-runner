$planning_rules

Understand the existing project only as much as needed to plan this goal:
$goal

Project root:
$root

Project files:
$outline

Progress:
$progress_json
$planning_feedback

This is the dedicated project-understanding turn. Do not create TODOs yet.

For any project size:
- Start from the supplied outline as a map and identify only the areas likely relevant to the goal.
- Search or list narrowly before reading deeply. Read relevant entry points, interfaces, configuration, tests, expected outputs, and direct dependencies only as needed.
- Expand to another area only when current evidence shows it is relevant.
- Do not try to read the whole repository or achieve exhaustive understanding.
- Stop once there is enough evidence to make a reliable implementation plan.
- Do not modify project files.

For repair planning, focus first on current project state and validator feedback, then inspect only what is needed to explain the unresolved failure.

End with a concise planning summary of the relevant architecture, files, constraints, and concrete changes that appear necessary. Do not output TODO JSON in this turn.
