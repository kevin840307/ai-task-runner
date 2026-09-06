{% include "stages/review.md" %}

Additional E2E review criteria:
- Review `result/blueprint/export/` as a project-agnostic E2E Blueprint, not as static-analysis inventory.
- Treat only concrete MAJOR/CRITICAL defects in the current TODO as blocking: wrong/missing business flow, materially inconsistent Flow↔Case behavior, non-observable oracle, unsupported PROVEN/SUPPORTED claim, or an evidence-proven boundary/failure/retry/async/idempotency/mode distinction that is materially missing.
- Do not require source code, code coverage, fixed case counts, class/function/SQL inventories, or speculative edge cases.
- `ASSUMPTION` plus an explicit open question is valid when evidence is unavailable.
