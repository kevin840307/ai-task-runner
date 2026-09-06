{% include "stages/execution.md" %}

Additional E2E Blueprint contract:
- Read `result/system/workflow1/preflight.yaml` first and complete only the current TODO. Planning defines business-flow work; Execute may perform deep discovery across any relevant project/module/service.
- For large or multi-project workspaces, first identify the minimum relevant project/module boundaries, then trace only the call/data paths needed for this TODO. If the backend exposes subagents, you may delegate independent module/service investigations in parallel and merge only evidence-backed conclusions. Subagents are optional, never required.
- Model business/user-observable E2E behavior, not repository inventory. Source code is evidence, not a completeness denominator; docs/SPEC/OpenAPI/SQL/DDL/config/workflow/tests/runtime evidence are equally valid when authoritative.
- Preserve valid prior Blueprint content and merge only the current TODO contribution.
- Maintain only the canonical portable pack under `result/blueprint/export/`:
  - `architecture.yaml`: root `flows:` (optional `components:` / `open_questions:`). Each flow: `id`, `title`, `trigger`, meaningful `steps`, observable `terminal_outcomes`, evidence refs when available.
  - `e2e_cases.yaml`: root `cases:`. Each case: `id`, `title`, `flow_ref`, `intent`, `given`, `when`, `then`, `evidence_level`; use `evidence_refs: [E001, ...]` to reference rows in `evidence_index.yaml`. `source_refs` may contain direct source locators such as `material://...`, but they are NOT Evidence IDs.
  - `evidence_index.yaml`: root `evidence:`. Each evidence row: `id`, `kind`, `source`, `claim`. The `id` is the stable traceability key; `source` is the underlying locator.
  - `manifest.yaml`: minimal metadata only; Final Python owns final counts/fingerprints.
- Do not invent unsupported behavior. Use `ASSUMPTION` plus an explicit open question when evidence is insufficient.
- Prefer materially distinct observable cases; do not enumerate every class/function/SQL merely to inflate coverage.
- Prefer Traditional Chinese for human-readable titles/descriptions when practical; keep technical identifiers unchanged.
