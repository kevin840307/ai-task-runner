$planning_rules

Understand the existing project only as much as needed to plan this goal:
$goal

Project root:
$root

Progress:
$progress_json
$planning_feedback

This is the dedicated project-understanding turn. Do not create TODOs yet.

For any project size:
- Start from the project root and identify only the areas likely relevant to the goal.
- Search or list narrowly before reading deeply. Read relevant entry points, interfaces, configuration, tests, expected outputs, and direct dependencies only as needed.
- Expand to another area only when current evidence shows it is relevant.
- Do not try to read the whole repository or achieve exhaustive understanding.
- Stop once there is enough evidence to make a reliable implementation plan.
- Do not modify project files.

For repair planning, use this authority order:
- The original goal and acceptance criteria are authoritative.
- The latest validator failure identifies what is still incorrect.
- The existing implementation is evidence, not a specification; do not preserve or complete a design merely because it already exists.
- Inspect only what is needed to explain the unresolved failure and prefer the smallest repair that moves the project back toward the original goal.

End with a concise planning summary of the relevant architecture, files, constraints, and concrete changes that appear necessary. Do not output TODO JSON in this turn.
