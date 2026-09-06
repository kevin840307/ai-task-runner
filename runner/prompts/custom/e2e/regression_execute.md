# Regression Test Task Execution

Goal: {{ goal }}
Project root: {{ project.root }}

Current TODO:
{{ task | tojson }}

Read `result/system/workflow2/preflight.yaml` first. The sibling `../material/` directory is read-only source evidence. If `../material/e2e_blueprint/` (or another Blueprint path named by preflight) exists, treat it as a high-value seed only; verify relevant claims against source/material truth before relying on them.

Execution rules:
- Work directly in the writable Test Project under this workspace.
- Generate or repair runnable regression tests for the current TODO; preserve unrelated valid tests.
- Prefer fewer high-confidence business tests over speculative tests created only to inflate coverage.
- Never modify `../material/`, `Runner E2E framework files`, `E2E_COVERAGE.yaml`, Runner state, or coverage policy.
- Never manually fabricate/edit a coverage report. Real coverage is produced later by Final Python execution.
- Assertions must verify meaningful business outcomes/state, not only that code executed or returned non-null.
- Do not mock components that are part of the SUT when the real test topology is expected to traverse them.
- Maintain `result/regression/manifest.yaml` incrementally. Each generated test entry must include at least: `id`, `intent`, and `test_ref`; add method/class/source refs when useful.
- When the TODO is already satisfied by a valid existing test, preserve it and update only the manifest if needed.

Finish only the current TODO. Do not perform final validation yourself.

## Language contract

- Prefer Traditional Chinese (zh-TW) for human-readable output fields when practical, especially `title`, `description`, `intent`, `role`, `claim`, summaries, review reasons, and open questions.
- Keep machine/technical identifiers unchanged: IDs, YAML keys, enum values, file paths, code symbols, API/SQL/table/class/function names, protocol/status tokens, and test references.
- Do not translate identifier values such as `FLOW-001`, `critical`, `SUPPORTED`, endpoint paths, method names, or SQL object names.
