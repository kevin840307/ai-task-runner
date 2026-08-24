$planning_rules

Create the implementation plan now without using any tools or inspecting more files.

Goal:
$goal

Project root:
$root

Progress:
$progress_json

$source_instruction

Inspection summary when available:
$inspection_summary

Produce the best concrete $planning_mode plan possible from the evidence already available.
For repair planning, keep the original goal authoritative, use the latest validator failure to identify the unresolved defect, and treat the existing implementation only as evidence. Do not preserve or complete an existing design merely because it already exists; prefer the smallest repair that returns the project toward the original goal. Each repair TODO must own only its relevant validator failures and acceptance criteria; do not duplicate unrelated failures or later-TODO work into it. When multiple reported failures share one underlying contract or root cause, prefer one coherent repair TODO for that shared cause instead of separate symptom-level TODOs.
Do not create standalone inspection, understanding, analysis, review, or check-only TODOs unless the goal explicitly requests that work or artifact. Otherwise keep any needed local inspection inside the implementation TODO that needs it. Do not create TODOs whose primary purpose is to run, inspect, or modify the final validator; the Runner owns final validation after implementation TODOs.
Every TODO must create or modify one concrete observable project result requested by the goal.
Each TODO must be one coherent implementation increment: large enough to produce an independently valuable observable result, and small enough to complete and review in one focused execution turn.
Split work only when each part has independent delivery value and can be completed and reviewed without relying on the other part's unfinished behavior. Keep an operation together with its required error handling and edge cases.
Do not create umbrella TODOs that implement the whole goal or absorb work that belongs to later TODOs.
Return at least $minimum_tasks ordered task(s), using only as many tasks as the goal's real deliverables require. Never split work to target a task count or manufacture preparation/read/check tasks.
Keep each TODO self-contained so its Executor can perform only the local inspection needed for that task.
