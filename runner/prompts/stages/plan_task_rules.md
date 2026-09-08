For repair planning, address only unresolved validator/review gaps, keep the original goal authoritative, preserve already-correct work, and group failures that share one root cause.
Create the minimum number of coherent implementation TODOs required by the goal.

Each TODO must:
- produce one observable project artifact or behavior now;
- be independently executable and independently reviewable;
- include enough local context that execution does not need to rediscover the entire project;
- name the affected component/project boundary when the task spans multiple projects;
- contain concrete task-specific acceptance criteria that can be checked from project evidence;
- include focused test creation/update in the TODO only when testing is materially part of proving that change.

For complex work, split TODOs at meaningful responsibility, dependency, or verification boundaries. Do not split a single atomic change into tiny file-by-file TODOs, and do not create umbrella TODOs that hide several unrelated changes.
Do not create inspection-only, review-only, validator-only, preparation, or orchestration TODOs unless the goal explicitly requires that deliverable.
Acceptance criteria must describe the TODO's resulting project artifact or behavior now. Do not use criteria about future Stage behavior, review/repair/validator outcomes, or available workflow mechanics.
