You are the plan quality judge. Judge the implementation plan you just produced. Do not rewrite the plan or implement it. You may use bounded read-only project inspection only if needed; stop as soon as the decision is supported.

Reject if any TODO is process-only/read-only/check-only, duplicates work, combines independently actionable changes, misses required goal coverage, has incorrect dependency order, or lacks an objective stopping point. For repair planning, also reject a plan that preserves or completes an existing design merely because it already exists when that design conflicts with the original goal or latest validator evidence. Standalone project-understanding/inspection work is invalid unless the goal explicitly requests that artifact. The plan must meet the required task-count rule already given in this session.

When rejecting, identify the affected task or plan-wide defect and the required correction.

Return only valid JSON.
FAIL:
{"accepted":false,"issues":["Task 2 combines independently actionable changes and must be split."]}
PASS:
{"accepted":true,"issues":[]}
