# E2E Regression Generation

Use the user's Regression Request plus available project/material evidence to generate or repair
runnable regression tests for the whole requested scope.

- For large or multi-project workspaces, discover relevant project/module/service boundaries first.
- If the backend supports subagents/delegation, you may delegate independent investigations or
  test-generation slices and merge only verified results. Subagents are optional.
- Generate runnable tests with meaningful business assertions. Do not mock SUT components that the
  claimed E2E path is supposed to traverse.
- Maintain `result/regression/manifest.yaml`; every generated test needs `id`, `intent`, `test_ref`.
- `E2E_COVERAGE.yaml` is user-owned policy. Never modify it, weaken thresholds, fabricate reports,
  or bypass configured execution commands.
- Prefer fewer evidence-backed tests over speculative cases added only to increase coverage.
- Prefer Traditional Chinese for human-readable descriptions; keep technical identifiers unchanged.
- Finish the whole requested regression task. Runner `system/mixed` owns planning, review/recovery,
  deterministic file validation, and final AI validation.
