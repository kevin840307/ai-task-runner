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

Create an ordered $planning_mode plan from concrete deliverables, not from phases of thought.

Rules:
1. Every TODO must create or modify one concrete, observable project result requested by the goal.
2. Reading, investigation, design reasoning, review, and running existing checks are execution steps or acceptance evidence, not standalone TODOs, unless the goal explicitly requests a concrete artifact or changed behavior from that work.
3. Keep one coherent deliverable per TODO. Split work whose parts can be implemented, reviewed, or fail independently.
4. Make every TODO self-contained: put required task-specific context in its description so execution does not need the original goal or planning output.
5. State the exact result in deliverable and objective stopping evidence in acceptance_criteria.
6. Keep dependencies ordered and changes minimal. Preserve existing behavior and public contracts unless the goal requires otherwise.
7. Do not create runner-owned final validation, retry, generic cleanup, or check-only TODOs.
8. Return at least $minimum_tasks task(s). Add more only when the remaining concrete deliverables require them; never pad with process tasks.

For repair planning, include only concrete changes needed for unresolved validator failures.
Do not implement, ask questions, use tools, or write files during planning.
Every task must include this acceptance criterion: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.
Before returning, reject and rewrite the plan if any TODO has no concrete observable result or combines multiple independently verifiable deliverables.

Return only valid JSON in this shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Task-specific context and one coherent change.","deliverable":"The exact observable project result.","acceptance_criteria":["Objective completion evidence","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
