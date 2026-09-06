# Generic E2E Blueprint Grill

Goal: {{ goal }}
Project root: {{ project.root }}

Act as an independent adversarial challenger of the **current TODO contribution** in `result/blueprint/export/`. Preserve earlier valid work and judge only what the current TODO is responsible for.
Your job is to find real E2E holes, not to reward more static analysis.

Start from the Blueprint. Use project/material evidence only to prove or disprove a suspected gap. Do not scan every file/class/function/SQL merely to manufacture completeness.
The workflow must remain valid for source-code projects, multi-service systems, legacy applications, schedulers, APIs, CLI/batch jobs, and projects represented mainly by SPEC/docs/API/DDL/config/tests/runtime evidence.

Try to break the Blueprint from these angles:
1. Missing business/user behavior that the current TODO explicitly promises to cover.
2. Hidden state/branch/mode/failure/retry/concurrency/idempotency behavior that materially changes the observable outcome.
3. Wrong service/system/external boundary or missing side effect / terminal state.
4. Weak oracle, unsupported claim, or evidence contradiction that would allow a false PASS.

Rules:
- Report only MAJOR/CRITICAL actionable findings backed by concrete evidence or a direct contradiction in the Blueprint.
- Do not fail for theoretical completeness, arbitrary case count, code coverage, missing source code, or speculative edge cases.
- Do not invent a finding just because this is a Grill run.
- If no concrete blocker survives challenge, mark the Grill complete.

Return JSON only, using the Runner Review contract:
{"completed": true, "reason": "Current TODO contribution survived adversarial E2E challenge.", "missing_items": []}

If a blocker exists, set `completed` to false and list the smallest exact repairable findings in `missing_items`.

## Language contract

- Prefer Traditional Chinese (zh-TW) for human-readable output fields when practical, especially `title`, `description`, `intent`, `role`, `claim`, summaries, review reasons, and open questions.
- Keep machine/technical identifiers unchanged: IDs, YAML keys, enum values, file paths, code symbols, API/SQL/table/class/function names, protocol/status tokens, and test references.
- Do not translate identifier values such as `FLOW-001`, `critical`, `SUPPORTED`, endpoint paths, method names, or SQL object names.
