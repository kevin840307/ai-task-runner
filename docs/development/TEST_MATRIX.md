# Test Matrix

Version: 1.2.33

## Contract areas
- CLI/API request validation and YAML script mode.
- Qwen/OpenCode backend command/session parsing; Qwen stdin-only prompt and EOF.
- Plan Stage structured task contract, same/fresh recovery, minimum TODO contract, bounded scope, and the no-Understand/no-Judge flow.
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

## Qwen live reliability
`python tool/qwen_live_reliability.py` is the opt-in real-Qwen reliability gate. It verifies process restart/resume with the same durable session, validator-driven repair, an injected transient API outage without replacing the healthy session, multi-TODO checkpoint resume without repeating completed work, independent Final AI 3/2 voting in three distinct sessions, mixed Python + Final AI validation, and bounded timeout recovery.

Use `python tool/qwen_live_reliability.py --hours 24 --pause 30` for the 24-hour soak. A claim of 24-hour stability requires the command to run for the full wall-clock duration and produce a passing `summary.json`; passing the fault-injection probes alone is strong preflight evidence but is not a substitute for elapsed time. By default, soak iterations use the deterministic Python validator for speed and signal clarity; add `--soak-final-ai-every N` to run mixed Python + Final AI 3/2 validation every N soak iterations, for example `--soak-final-ai-every 5`. Per-run projects, concise console JSONL, Runner events, state, and diagnostics are stored under `.ai-task-runner-live/<timestamp>/`.
