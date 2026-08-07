$planning_rules

Create the implementation plan now without using any tools or inspecting more files.

Goal:
$goal

Project root:
$root

Project files already supplied by the runner:
$outline

Progress:
$progress_json

$source_instruction

Inspection summary when available:
$inspection_summary

Produce the best concrete $planning_mode plan possible from the evidence already available.
Project-wide understanding is complete for planning purposes. Do not turn project discovery already performed during planning into Executor work.
Do not create standalone inspection, understanding, analysis, review, or check-only TODOs unless the goal explicitly requests that artifact as an end result.
Every TODO must create or modify one concrete observable project result requested by the goal.
Split independently implementable or verifiable changes so a smaller model can complete one coherent step at a time.
Return at least $minimum_tasks ordered task(s); satisfy the minimum only with real deliverables.
If more tasks are needed to satisfy the minimum, split concrete implementation behavior or independently verifiable project changes; never manufacture preparation/read/check tasks to increase the count.
Keep each TODO self-contained so its Executor can perform only the local inspection needed for that task.
Every task must include this acceptance criterion: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.
Return only valid JSON in this shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Task-specific context and one focused change.","deliverable":"The exact observable project result.","acceptance_criteria":["Objective completion evidence","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
