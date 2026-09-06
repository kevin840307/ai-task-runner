{% include "stages/grill.md" %}

Additional E2E Grill criteria:
- Challenge only the current TODO contribution in `result/blueprint/export/`.
- Look for evidence-backed MAJOR/CRITICAL E2E holes: missing promised business behavior, materially different branch/mode/failure/retry/concurrency/idempotency behavior, wrong system/external boundary, missing terminal side effect/state, weak oracle, or evidence contradiction.
- Do not manufacture findings through repository-wide static analysis, arbitrary completeness targets, fixed case counts, or code coverage.
- If no concrete blocker survives challenge, PASS immediately.
