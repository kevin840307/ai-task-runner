$planning_rules

Refine this task plan for the same goal.

Goal:
$goal

Project root:
$root

Project files:
$outline

Progress:
$progress_json

Current task JSON:
$tasks_json

Return only valid JSON with the same schema. This is $planning_mode planning. Keep at least $minimum_tasks task(s).
Keep the plan ordered and AI-executable.
Remove standalone survey-only TODOs. When existing code or architecture must be understood, include read-only inspection as acceptance criteria on the first concrete deliverable task.
If a TODO only inspects, analyzes, plans, designs, reviews, runs validation, runs tests, or compares fixtures, rewrite it into acceptance criteria for the nearest concrete deliverable task.
Understanding the project is required, but it is internal work for a deliverable task. Never output a TODO whose result is only understanding, notes, inspection, analysis, review, or validation.
If the user goal includes process verbs such as inspect, understand, test, validate, compare, review, finalize, or cleanup, treat them as acceptance criteria unless the goal explicitly asks to create or modify a concrete artifact for that process.
Split any task that contains multiple independently verifiable deliverables.
Every TODO must create or modify a concrete project deliverable requested by the goal. Put that concrete result in the non-empty deliverable field.
Every TODO must be self-contained for execution: its description must include the task-specific context needed to act without rereading the original goal or planning output.
Its deliverable must define the exact end result, and its acceptance criteria must provide enough evidence to know when to stop.
Repeat only genuinely goal-wide compatibility, safety, and non-regression constraints in every task's acceptance criteria so the runner can pass them as a concise shared constraint summary.
Remove tasks whose only purpose is final validation, review, retry, or comparing outputs to reference fixtures. Put those checks into acceptance criteria unless the goal explicitly asks to create or change a validator, test, or report artifact.
Running an existing validator or test command is not a standalone TODO; the runner runs final validation automatically.
Preserve useful task granularity. Do not merge distinct deliverables only to shorten the list. For repair planning, remove unnecessary tasks and keep only concrete work required by remaining validator failures.
split enough that a smaller model can complete one coherent step at a time without taking over later TODOs.
Do not add generic cleanup, final review, or check-only tasks.
Before returning JSON, reject your own plan if any TODO has no concrete file, command, data contract, generated output, report, documentation, or user-facing behavior to create or modify.
Do not return a plan with only process or inspection tasks. Such a plan is invalid; rewrite it into concrete implementation/documentation/output tasks.
Do not implement, ask questions, use tools, or write files during planning.
Every task must include this acceptance criterion: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.

Return only this JSON shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Create or modify one coherent result required by the remaining work.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
