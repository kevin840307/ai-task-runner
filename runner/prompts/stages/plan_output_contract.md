Available task Stages:
{{ planning.available_stages | tojson }}

Return only valid JSON in this shape, without Markdown or explanation:
{"tasks":[{"title":"Deliverable","description":"Task-specific context and one focused change.","deliverable":"Exact observable project result.","acceptance_criteria":["Concrete task-specific completion evidence"],"steps":["stage_name","review_stage_name"]}]}

For each TODO, choose the smallest ordered `steps` sequence needed from Available task Stages. Use only listed Stage names. When any available Stage has `"mode":"write"`, each TODO must include a write Stage. When a review Stage is available, it must be the final step. Use optional Stages only when they add value to that TODO; do not add a Stage merely because it exists.
Acceptance criteria must be task-specific and objectively checkable. Global architecture, compatibility, safety, and minimum-code rules are inherited automatically; do not repeat them in every task.
Do not make acceptance criteria depend on future Stage behavior, review/repair/validator outcomes, or available workflow mechanics. Those are orchestration details, not the TODO's deliverable evidence.
