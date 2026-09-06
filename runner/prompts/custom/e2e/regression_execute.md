{% include "stages/execution.md" %}

Additional E2E Regression contract:
- Read `result/system/workflow2/preflight.yaml` first. Treat any supplied Blueprint as a high-value seed, but verify claims against current material/source truth before relying on it.
- Generate or repair runnable regression tests only for the current TODO; preserve unrelated valid tests.
- Never modify read-only material, Runner E2E framework files, Runner state, `E2E_COVERAGE.yaml`, or coverage policy; never fabricate coverage reports.
- Assertions must prove meaningful business outcomes/state. Do not mock SUT components that the claimed E2E topology is meant to traverse.
- Maintain `result/regression/manifest.yaml` incrementally; each generated test needs at least `id`, `intent`, and `test_ref`.
- Prefer fewer high-confidence business tests over speculative tests added only to increase coverage.
- Prefer Traditional Chinese for human-readable descriptions when practical; keep technical identifiers unchanged.
