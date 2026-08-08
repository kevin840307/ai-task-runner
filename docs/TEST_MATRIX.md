# Test Matrix

Version: 1.1.1

## Contract areas
- CLI/API request validation and YAML script mode.
- Qwen/OpenCode backend command/session parsing; Qwen stdin-only prompt and EOF.
- Planning same-session/fresh fallback, minimum TODO count, bounded scope, Refiner/Judge fail-soft.
- Executor fresh/rebuilt Goal context, same-session short continuation, Current-TODO-only scope.
- Review/read-only/finalize behavior.
- Generic structured result extraction and strict stage schemas.
- Deterministic validator invocation, validator args, timeout/retry, Final AI validation.
- Project policy/protected subtree/snapshot restore/Git guard.
- Debug current/last/bounded history and terminal single-line rendering.
- Resume/state/no-progress/recovery behavior.

## Smoke/examples policy contract
Every `examples/*/project` and `smoke/*/project` root contains `.ai-task-runner.yaml`. The policy itself is automatically protected. Immutable input/reference data is explicitly protected when present, while intended output/source targets remain writable.

## Validator contract
Example/smoke validators use the local `validator_interface.py` reporting contract. Validators primarily test observable deliverables. Only tests whose purpose is Runner planning may assert TODO/state structure.
