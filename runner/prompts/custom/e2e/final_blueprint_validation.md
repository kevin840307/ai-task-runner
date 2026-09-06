# Final Independent Generic E2E Blueprint Challenger

Goal: {{ goal }}
Project root: {{ project.root }}

Final Python contract validation has passed. Start with `result/system/workflow1/final_ai_context.yaml`, then inspect only the exact project/material evidence needed to confirm or reject a concrete finding.
Do not inspect Runner E2E framework files, `.ai-task-runner`, generated Runner state, or framework implementation as product evidence.

This workflow is intentionally project-agnostic. Do **not** require source-code/static-analysis artifacts when the project can be understood from SPEC, documentation, API definitions, SQL/DDL, configuration, workflow files, tests/samples, runtime evidence, or user requirements.

Reject only concrete MAJOR/CRITICAL semantic defects, for example:
- a clearly important business/user flow in the supplied scope is missing;
- a case claims an outcome that contradicts its cited evidence;
- a case is not E2E-observable or has no meaningful oracle;
- materially different success/failure/mode/retry/concurrency behavior is incorrectly merged when evidence proves the distinction;
- internal/external boundaries are materially wrong for the intended E2E test;
- a `PROVEN`/`SUPPORTED` claim has no usable evidence;
- the Blueprint is dominated by implementation inventory/static-analysis detail instead of testable business behavior.

Do not fail for theoretical completeness, code coverage, lack of a particular programming-language artifact, or speculative edge cases. `ASSUMPTION` items are allowed when clearly labeled and accompanied by an open question.

Return JSON only:
{"passed": true, "reason": "No concrete major semantic defect found.", "missing_items": [], "checks_run": ["business-flow coverage", "observable oracle quality", "evidence consistency", "project-agnostic scope check"], "suggested_checks": []}

If a blocking defect exists, set `passed` to false and list exact actionable defects in `missing_items`.

## Language contract

- Prefer Traditional Chinese (zh-TW) for human-readable output fields when practical, especially `title`, `description`, `intent`, `role`, `claim`, summaries, review reasons, and open questions.
- Keep machine/technical identifiers unchanged: IDs, YAML keys, enum values, file paths, code symbols, API/SQL/table/class/function names, protocol/status tokens, and test references.
- Do not translate identifier values such as `FLOW-001`, `critical`, `SUPPORTED`, endpoint paths, method names, or SQL object names.
