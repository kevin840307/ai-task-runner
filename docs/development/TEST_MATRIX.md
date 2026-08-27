# Test Matrix

Version: 1.2.34

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
`python tool/qwen_live_reliability.py` is the opt-in real-Qwen reliability gate. It verifies process restart/resume with the same durable session, validator-driven repair, protected-file policy handling under a conflicting prompt, an injected transient API outage without replacing the session before recovery, multi-TODO checkpoint resume without repeating completed work, YAML List process restart/resume without repeating a completed item, independent Final AI 3/2 voting in three distinct sessions, mixed Python + Final AI validation, and bounded timeout recovery.

Use `python tool/qwen_live_reliability.py --hours 24 --pause 30` for the 24-hour soak. On Windows, `run_qwen_live_reliability.bat` runs the recommended 0.5-hour high-density gate when called without arguments; arguments replace that default, for example `run_qwen_live_reliability.bat --hours 24 --high-density --require-transient`. A claim of 24-hour stability requires the command to run for the full wall-clock duration and produce a passing `summary.json`; the summary records `soak_elapsed_seconds` as evidence. Passing the fault-injection probes alone is strong preflight evidence but is not a substitute for elapsed time. Add `--sandbox` when the whole live gate should exercise Qwen sandbox mode. For convergence, use `python tool/qwen_live_reliability.py --hours 0.5 --high-density --require-transient`, which lowers the pause, caps ordinary Qwen calls with `--agent-timeout 180` and `--planning-timeout 180`, and mixes Final AI validation, transient API recovery, timeout recovery, YAML List restart/resume, and periodic sandbox runs into the short soak. A high-density run fails unless every mixed category is actually observed. The individual frequencies are configurable with `--soak-final-ai-every N`, `--soak-transient-api-every N`, `--soak-timeout-every N`, `--soak-yaml-every N`, and `--soak-sandbox-every N`. Add `--example-smoke-project` to copy and run `examples/01_basic_python_validator/project` as a final real-agent smoke after the reliability probes/soak, or pass a project path to run a different example; add `--example-smoke-workflow path/to/workflow.yaml` when that example must run a custom workflow such as `tool/workflows/skill_prompt_review_chain.yaml`. For broader coverage, repeat `--example-smoke-matrix-project` and `--example-smoke-matrix-workflow` to run the cross product of real example projects and workflow YAML files after the probes/soak. This is opt-in so established soak defaults do not change. Per-run projects, concise console JSONL, Runner events, state, and diagnostics are stored under `.ai-task-runner-live/<timestamp>/`.

Example matrix command:

```powershell
python tool/qwen_live_reliability.py --hours 0.25 --high-density --require-transient --example-smoke-matrix-project examples/01_basic_python_validator/project --example-smoke-matrix-project examples/10_skill_prompt_review_workflow/project --example-smoke-matrix-workflow runner/workflow/builtin/file.yaml --example-smoke-matrix-workflow runner/workflow/builtin/mixed.yaml --example-smoke-matrix-workflow tool/workflows/skill_prompt_review_chain.yaml
```

Windows convenience BAT files live under `tool/`: `qwen_live_reliability_0_5h.bat` targets a 95% confidence preflight, and `qwen_live_reliability_24h.bat` targets 99.99% confidence after the full 24-hour wall-clock run. The percentages are confidence targets for a passing run, not unconditional guarantees; the emitted `summary.json` remains the evidence.
