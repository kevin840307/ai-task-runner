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

Use only the goal, project root, project outline, progress, and planning feedback shown here.
Do not use tools during planning.
Always return valid JSON even if the goal is ambiguous or the project outline is incomplete.
When uncertain, choose the smallest conservative task list that can still complete the goal.
Do not create standalone survey-only TODOs. When existing code or architecture must be understood, include read-only inspection as acceptance criteria on the first concrete deliverable task.
If a TODO would only inspect, analyze, plan, design, review, run validation, run tests, or compare fixtures, make it acceptance criteria for the nearest concrete deliverable task instead.
Understanding the project is required, but it is internal work for a deliverable task. Never output a TODO whose result is only understanding, notes, inspection, analysis, review, or validation.
If the user goal includes process verbs such as inspect, understand, test, validate, compare, review, finalize, or cleanup, treat them as acceptance criteria unless the goal explicitly asks to create or modify a concrete artifact for that process.
Identify concrete deliverables from the goal and project, then split work into independently executable tasks with verifiable outcomes.
Return at least 6 ordered tasks. More tasks are allowed when the goal requires them. Each task must remain a coherent, independently reviewable work unit.
Do not collapse a broad or multi-file goal into one "build everything" task.
Prefer tasks that produce or modify one coherent deliverable. If a task contains multiple independently verifiable deliverables, split it.
Every TODO must create or modify a concrete project deliverable requested by the goal. Put that concrete result in the non-empty deliverable field.
Do not create tasks for runner-owned final validation, review, retry, or comparing outputs to reference fixtures. Put expected checks into acceptance criteria unless the goal explicitly asks to create or change a validator, test, or report artifact.
Running an existing validator or test command is not a standalone TODO; the runner runs final validation automatically.
Do not add generic cleanup, final review, or check-only tasks.
For complex changes, split by concrete deliverables and their dependencies so a smaller model can complete one useful project change at a time.
Before returning JSON, reject your own plan if any TODO has no concrete file, command, data contract, generated output, report, documentation, or user-facing behavior to create or modify.
Do not return a plan with only process or inspection tasks. Such a plan is invalid; rewrite it into concrete implementation/documentation/output tasks.
Each task must be ordered, independently executable, meaningful, and have clear acceptance criteria describing completion evidence.
Include this acceptance criterion in every task: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.
Return the final tasks JSON directly instead of writing files during planning.
Do not create, edit, delete, or rename project implementation files during planning; implementation happens only after tasks are returned.
Do not implement, ask questions, or wait for input. Make reasonable assumptions from the project.
Return at least 6 tasks. Never return fewer than 6 tasks.
Before answering, self-check that the JSON parses and that every task has title, description, deliverable, and acceptance_criteria, and that the array contains at least 6 tasks.

Return only this JSON shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable 1","description":"Create or modify one coherent result required by the goal.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]},{"title":"Deliverable 2","description":"Create or modify one coherent result required by the goal.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]},{"title":"Deliverable 3","description":"Create or modify one coherent result required by the goal.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]},{"title":"Deliverable 4","description":"Create or modify one coherent result required by the goal.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]},{"title":"Deliverable 5","description":"Create or modify one coherent result required by the goal.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]},{"title":"Deliverable 6","description":"Create or modify one coherent result required by the goal.","deliverable":"A concrete project result for this task.","acceptance_criteria":["The declared deliverable is complete","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
