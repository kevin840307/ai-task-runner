# Generic E2E Blueprint Review

Goal: {{ goal }}
Project root: {{ project.root }}

Review the current TODO output in `result/blueprint/export/` as part of a **project-agnostic E2E test blueprint**.
Start from the Blueprint itself and `result/system/workflow1/preflight.yaml`. Inspect project/material evidence only when needed to verify a concrete concern.

This is a normal quality review, not repository-wide static analysis.
Do **not** require source code, class/function/SQL inventories, code coverage, a fixed case count, or language-specific artifacts.

Check only concrete MAJOR/CRITICAL defects relevant to the current TODO:
- the TODO's intended business/user E2E behavior is missing or materially wrong;
- a Flow and its Cases disagree materially;
- Given/When/Then does not end in a meaningful observable oracle;
- evidence refs do not support a PROVEN/SUPPORTED claim;
- duplicate/noise cases hide the actual behavioral distinction;
- an important boundary, failure, retry, async, idempotency, or mode distinction is missing **when supplied evidence proves it matters**;
- the output describes implementation inventory instead of testable E2E behavior.

Do not invent missing items. `ASSUMPTION` + an explicit open question is valid when evidence is unavailable.
If there is no concrete blocking defect for the current TODO, mark it complete.

Return JSON only, using the Runner Review contract:
{"completed": true, "reason": "No concrete major review defect found for the current TODO.", "missing_items": []}

If blocking defects exist, set `completed` to false and put only exact actionable defects in `missing_items`.

## Language contract

- Prefer Traditional Chinese (zh-TW) for human-readable output fields when practical, especially `title`, `description`, `intent`, `role`, `claim`, summaries, review reasons, and open questions.
- Keep machine/technical identifiers unchanged: IDs, YAML keys, enum values, file paths, code symbols, API/SQL/table/class/function names, protocol/status tokens, and test references.
- Do not translate identifier values such as `FLOW-001`, `critical`, `SUPPORTED`, endpoint paths, method names, or SQL object names.
