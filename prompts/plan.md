$planning_rules

Plan only the remaining work for this goal:
$goal

Project root:
$root

Project files:
$outline

Progress:
$progress_json
$planning_feedback

Create an ordered $planning_mode plan from concrete changes, not from phases of thought.

Rules:
1. Every TODO must create or modify one concrete, observable project result requested by the goal.
2. Reading, investigation, design reasoning, review, and merely running existing checks are execution steps or acceptance evidence, not standalone TODOs, unless the goal explicitly requests a concrete artifact or changed behavior from that work.
3. Split work whenever changes can be implemented, reviewed, verified, retried, or fail independently. Multiple TODOs may modify the same file; file count does not determine task count.
4. Small TODOs are valid when they make a real bounded change. Do not merge concrete independent changes merely because they share a file or component.
5. Make every TODO self-contained: put required task-specific context in its description so execution does not need the original goal or planning output.
6. State the exact result in deliverable and objective stopping evidence in acceptance_criteria.
7. Keep dependencies ordered and changes minimal. Preserve existing behavior and public contracts unless the goal requires otherwise.
8. Do not create runner-owned final validation, retry, generic cleanup, read-only inspection, or check-only TODOs.
9. Return at least $minimum_tasks ordered task(s). More tasks are allowed whenever the work has more independently actionable changes; never pad with process-only work.

For repair planning, include only concrete changes needed for unresolved validator failures.
Do not implement, ask questions, use tools, or write files during planning.
Every task must include this acceptance criterion: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.
Before returning, reject and rewrite the plan if any TODO has no concrete observable change, is only a read/check step, duplicates another TODO, or combines changes that can be implemented or verified independently.

Return only valid JSON in this shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Task-specific context and one focused change.","deliverable":"The exact observable project result.","acceptance_criteria":["Objective completion evidence","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
