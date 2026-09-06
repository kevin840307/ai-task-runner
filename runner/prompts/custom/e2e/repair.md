# Targeted E2E Workflow Repair

Goal: {{ goal }}
Project root: {{ project.root }}

{{ instructions }}

Exact failure feedback:
{{ previous.output }}

Repair contract for small models:
- Repair exactly one concrete failure family from the feedback; never regenerate an unrelated Stage.
- Preserve valid evidence, completed batches, and machine-owned denominators.
- Never delete required items merely to obtain PASS.
- Never modify source/SPEC/DDL/config/workflow materials, protected validation policy, framework files, or Runner state.
- If feedback names a batch/finding, inspect only that batch/finding and directly related evidence.
- For Grill findings, repair only OPEN CRITICAL/MAJOR items; MINOR is report-only.

Return a short repair summary after editing only the requested artifacts.

Repair convergence rule:
- Treat the latest Python Gate violations as authoritative diagnostics.
- If any reported violation still applies, make an actual artifact change that resolves it before claiming PASS.
- Never report a repair as complete merely by describing an intended change. Re-read the edited YAML and verify the violating field/shape is now different and valid.
- If the current artifact already satisfies the diagnostic because the Gate used an older snapshot, do not rewrite valid content just to create a change; state that it is already compliant and let the Python Gate re-evaluate the current filesystem.

## Language contract

- Prefer Traditional Chinese (zh-TW) for human-readable output fields when practical, especially `title`, `description`, `intent`, `role`, `claim`, summaries, review reasons, and open questions.
- Keep machine/technical identifiers unchanged: IDs, YAML keys, enum values, file paths, code symbols, API/SQL/table/class/function names, protocol/status tokens, and test references.
- Do not translate identifier values such as `FLOW-001`, `critical`, `SUPPORTED`, endpoint paths, method names, or SQL object names.
