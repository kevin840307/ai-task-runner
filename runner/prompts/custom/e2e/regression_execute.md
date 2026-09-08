# E2E Regression Generation / Execution

Use the user's Regression Request plus `result/e2e_spec/e2e_spec.yaml` when available to generate or repair runnable regression tests for the whole requested scope.

## Test-contract rules
- Every test must map to a verified Flow / Branch / Outcome and must assert at least one declared Outcome observation.
- Prefer actual business observations: DB state/data, API read-back, message/event, log, file/state. Log assertions should use correlation/request/job id plus keyword/regex/count when possible; a generic log line alone is not strong evidence.
- For large or multi-project workspaces, discover relevant project/module/service boundaries first. Subagents may handle independent slices, but the main agent must re-verify and integrate them.

## Mock boundary — strict
Define SUT as all user-specified source/projects/modules/services/DLLs covered by the E2E SPEC.

Allowed to mock/stub:
- Real dependencies outside the SUT, such as third-party URLs or external MQ/Kafka/NATS counterpart/transport boundaries.
- Dependencies explicitly proven `ownership: external`.

Forbidden to mock/fake/bypass:
- Any SUT component with source code: project/DLL/service/class/method/consumer/producer/repository/domain logic.
- A SUT HTTP endpoint/consumer merely because it is reached through URL/MQ/Kafka/NATS.
- Existing DB/test DB/repository/database paths. Run the real DB interaction and assert the result.
- `ownership: unknown` dependencies unless first proven external.

## No fake PASS / result injection
- Pre-trigger seed/precondition data is allowed.
- After the real trigger, never directly INSERT/UPDATE the final expected row/state to manufacture PASS.
- Never monkeypatch/replace internal SUT methods to return success, directly force terminal state, skip consumer/domain/repository paths, remove assertions, lower thresholds, change expected values to observed bugs, catch-and-ignore failures, or skip tests for PASS.
- Cleanup is allowed only after assertions and must not hide a failure.

## Execution
- Maintain `result/regression/manifest.yaml`; every generated test needs `id`, `intent`, `test_ref` and should retain E2E spec references where practical.
- `E2E_COVERAGE.yaml` is user-owned policy. Never modify it, weaken thresholds, fabricate reports, or bypass configured execution commands.
- Actually run tests/coverage/validators. Repair root causes in test/setup/integration as needed; do not turn failures into fake success.
- Prefer fewer evidence-backed E2E tests over speculative coverage-filling tests.
- Prefer Traditional Chinese for human-readable descriptions; keep technical identifiers unchanged.
- Finish the whole requested regression task. Runner `system/mixed` owns planning, review/recovery, deterministic file validation, and final AI validation.
