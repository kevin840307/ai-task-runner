$planning_rules

Continue the existing planning work. Rewrite the current draft using the judge feedback and already-known planning context; do not repeat repository inspection, defend the old plan, or preserve a task merely because it already exists.

Goal:
$goal

Project root:
$root

Progress:
$progress_json

Draft task JSON:
$tasks_json
$judge_feedback

Return a complete replacement task list for $planning_mode planning.
For repair planning, keep the original goal authoritative, use the latest validator failure to identify what remains incorrect, and treat the existing implementation only as evidence. Do not preserve or complete an existing design merely because it already exists; prefer the smallest repair that moves the project back toward the original goal. Keep each repair TODO limited to its own relevant validator failures and acceptance criteria; remove unrelated failures and later-TODO work from it. When multiple reported failures share one underlying contract or root cause, prefer one coherent repair TODO for that shared cause instead of separate symptom-level TODOs.

Quality gate:
1. Every TODO must create or modify one concrete, observable project result requested by the goal. For an implementation/change goal, remove any TODO whose deliverable can be satisfied without changing a requested project result.
2. Project-wide understanding was already completed in a dedicated planning turn before TODO creation. Treat any standalone task whose purpose is to obtain that understanding as invalid even if the draft contains it. Knowledge, findings, design decisions, review decisions, and existing checks are supporting steps, not standalone deliverables. Put any remaining task-specific inspection inside the concrete TODO that uses it unless the goal explicitly requests its artifact as an end result.
3. Split changes only when each part produces an independently valuable observable result and can be completed and reviewed without relying on another part's unfinished behavior. Multiple TODOs may modify the same file; never use file count as the task boundary.
4. Keep one coherent behavior together with its required error handling and edge cases. Merge fragmented, duplicate, or process-only tasks; do not merge genuinely independent deliverables merely because they share a file or component.
5. Each description must contain the task-specific context needed to execute it without rereading the original goal or draft plan.
6. Each deliverable must state the exact end result. Acceptance criteria must make the stopping point objectively clear.
7. Remove runner-owned final validation, retry, generic cleanup, read-only inspection, and check-only tasks unless the goal explicitly requests that artifact or changed behavior. Never create a TODO whose primary purpose is to run, inspect, or modify the final validator.
8. Keep dependencies ordered. Return at least $minimum_tasks task(s), using only as many tasks as the real deliverables require. Never split work to reach a target count or preserve/invent preparation/read/check tasks.
9. Include genuinely goal-wide compatibility, safety, and non-regression constraints consistently so they can be summarized for execution.

Before returning, independently reject and rewrite the plan if any TODO can finish without producing its requested project result, exists only to gather knowledge/check work, duplicates another TODO, or combines independently implementable or verifiable changes.
Do not implement, ask questions, use tools, or write files during planning.
Every task must include this acceptance criterion: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.

Return only valid JSON in this shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Task-specific context and one focused change.","deliverable":"The exact observable project result.","acceptance_criteria":["Objective completion evidence","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
