{% include "stages/execution.md" %}

Additional E2E Blueprint contract:
- Read `result/system/workflow1/preflight.yaml` first and complete only the current TODO.
- Model business/user-observable E2E behavior, not repository inventory. Source code is evidence, not a required completeness denominator; docs/SPEC/OpenAPI/SQL/DDL/config/workflow/tests/runtime evidence are equally valid when authoritative.
- Preserve valid prior Blueprint content and merge only the current TODO contribution.
- Maintain only the canonical portable pack under `result/blueprint/export/`:
  - `architecture.yaml`: root `flows:` (and optional `components:` / `open_questions:`). Every flow needs `id`, `title`, `trigger`, meaningful `steps`, observable `terminal_outcomes`, and evidence refs when available.
  - `e2e_cases.yaml`: root `cases:`. Every case needs `id`, `title`, `flow_ref`, `intent`, `given`, `when`, `then`, `evidence_level`, and evidence refs when available.
  - `evidence_index.yaml`: root `evidence:`. Every evidence row needs `id`, `kind`, `source`, and `claim`.
  - `manifest.yaml`: keep minimal metadata only; Final Python owns final counts/fingerprints.
- Do not invent unsupported behavior. Use `ASSUMPTION` plus an explicit open question when evidence is insufficient.
- Prefer a small set of materially distinct cases with meaningful observable outcomes; do not inflate case count or enumerate every class/function/SQL.
- Prefer Traditional Chinese for human-readable titles/descriptions when practical; keep technical identifiers unchanged.
