Create the implementation plan now from the project understanding and original goal already in this planning session.

Do not use tools or inspect more files. Do not restart project analysis.
Produce the best concrete $planning_mode plan from the evidence already gathered.
For repair planning, keep the original goal authoritative, use the latest validator failure to identify the unresolved defect, and treat the existing implementation only as evidence. Do not preserve or complete an existing design merely because it already exists; prefer the smallest repair that returns the project toward the original goal. Each repair TODO must own only its relevant validator failures and acceptance criteria; do not duplicate unrelated failures or later-TODO work into it.
Do not create standalone inspection, understanding, analysis, review, or check-only TODOs unless the goal explicitly requests that artifact as an end result.
Every TODO must create or modify one concrete observable project result requested by the goal.
Split independently implementable or verifiable changes so a smaller model can complete one coherent step at a time.
Do not create umbrella TODOs that implement the whole goal or absorb work that belongs to later TODOs.
Return at least $minimum_tasks ordered task(s); satisfy the minimum only with real deliverables.
If more tasks are needed to satisfy the minimum, split concrete implementation behavior or independently verifiable project changes; never manufacture preparation/read/check tasks to increase the count.
Keep each TODO self-contained so its Executor can perform only the local inspection needed for that task.
Every task must include this acceptance criterion: Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior.

Return only valid JSON in this shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Task-specific context and one focused change.","deliverable":"The exact observable project result.","acceptance_criteria":["Objective completion evidence","Use the current architecture, minimum code, clean code, low coupling, and preserve existing behavior"]}]}
