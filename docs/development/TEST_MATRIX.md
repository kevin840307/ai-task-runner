# Test Matrix

Version: 1.2.13

## Contract areas
- CLI/API request validation and YAML script mode.
- Qwen/OpenCode backend command/session parsing; Qwen stdin-only prompt and EOF.
- Planning same-session Understand/Finalize/Judge/Rewrite, read-only bounded inspection, unrecoverable-session fresh fallback, minimum TODO count, bounded scope, and planning quality-gate fail-soft.
- Executor fresh/rebuilt Goal context, cross-TODO resume with next-TODO-only prompts, same-TODO short continuation, delayed session rebuild after repeated recoverable failures, and Current-TODO-only scope.
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

## Prompt/validator alignment
Smoke/example prompts contain task-specific requirements only; generic Runner behavior such as autonomous inspection, retry, and verification is not repeated. Deterministic validators must not enforce hidden formatting or planning strategy. Every hard validator assertion should map to an explicit task requirement or an immutable fixture invariant; qualitative goals such as concision should normally be warnings unless the prompt gives a numeric limit.
