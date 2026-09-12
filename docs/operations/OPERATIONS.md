# Operations and Troubleshooting

Version: 1.2.66

## Long-running behavior
Defaults intentionally allow long model calls: runtime 7200s, planning 600s, validator 1200s, idle-after-change 900s. Recovery thresholds escalate behavior instead of terminating the run: task failures move through same-session retry, fresh-session retry, and replan; validator failures move through repair planning and fresh full replanning. Recovery is driven by errors, session availability, no-progress fingerprints, review, and final validation. Timeout failures use a stable semantic recovery key while retaining full backend stderr for debugging, preventing changing sandbox/container IDs from indefinitely resetting same-failure escalation.

## Common recovery paths
- Invalid structured JSON/schema -> send a short same-session JSON-only correction first; if still invalid, use the Stage-configured fresh fallback. Review model errors follow the normal Stage retry budget before an allowed fail-soft skip.
- Session unavailable/expired -> rebuild immediately. Recoverable model failures such as a single loop keep the current session; repeated loop/no-progress failures trigger a bounded fresh rebuild with required context.
- Executor crashes after changing files -> preserve coherent changes and let Review/next recovery decide.
- Review model/policy error -> use shared stage-aware same-session recovery first. Read-only mutations are restored by Safety and treated as a failed attempt, so Review retries instead of silently accepting a mutated run; when the configured Review retry budget is exhausted and skip is allowed, record review_skipped.
- Validator FAIL -> Repair Planning with validator feedback.
- Validator infrastructure failure -> retry; never PASS open.

## Qwen diagnostics
Qwen prompt is stdin-only. A non-zero Qwen exit may still contain useful stdout; the Runner records raw result/diagnostics and stage fail-soft behavior determines whether work can continue. Windows `3221226505` (`0xC0000409`) is a process fast-fail and is not considered a normal successful exit.

## Debug files
### Live output
- `<work-dir>/stream.log`: latest bounded subprocess stdout for detached local UI/live inspection. It is cleared for each new subprocess and overwritten as newer output arrives; it is not a complete transcript and must not be used to infer PASS/FAIL or routing.

- `current-prompt.txt`: active prompt; written immediately before the backend call.
- `last-prompt.txt`: prompt paired with the most recently finished call.
- `last-result.txt`: result/error/parse diagnostics paired with that call.
- `history/`: each prompt entry is written when the call starts; its matching result entry is written on completion/error.
History is bounded to 100 calls, 50 MiB total, 2 MiB per history entry; oversized entries preserve head and tail. Current/last files are not truncated by history limits.

## Terminal UI
Human status/detail text is converted to one line before spinner rendering so embedded `\n` from backend errors cannot flood the terminal. Raw JSON events and debug files keep full detail.

## What to collect for a bug
Provide state/event log, `stream.log` when live-output behavior matters, `current-prompt.txt`, `last-prompt.txt`, `last-result.txt`, relevant history pair, command line, and visible error. This normally reconstructs stage -> prompt -> model result -> parser/backend decision -> Runner recovery.

`runner-process.json` is a small detached-UI runtime identity marker owned by the top-level Supervisor. It stores `supervisor_pid`, the current `worker_pid`, `started_at`, `project_root`, and `work_dir`; worker restart updates `worker_pid`, and normal Supervisor exit removes the marker. The existing `active-process` marker remains Runner-internal child/orphan cleanup state. PID metadata is never Workflow state and must not drive PASS/FAIL, retry, session, routing, or resume decisions. To stop a detached run, create an empty `.ai-task-runner/stop.request`; the Supervisor checks it while the Worker is running and during restart backoff, terminates the Worker/owned child process, consumes the request, and exits 130. To continue, relaunch with `--resume`; to rerun from scratch, relaunch with `--force-new`.

Transient API/network/rate-limit outages use bounded exponential backoff per delay interval but no retry-count exhaustion; they preserve current state/session. Persistent model/session problems use the normal reuse-then-rebuild policy.

Safety snapshot temp directories use `ai-task-runner-readonly-*` / `ai-task-runner-protect-*`. Normal Stage completion removes them immediately; startup also removes stale abandoned snapshots so abnormal process termination does not accumulate them indefinitely.

### Worker crash cleanup

After an abnormal worker exit, the supervisor cleans active child-process markers from the actual durable work directories returned for that Run. This includes each YAML List child (`.../script/NNN/active-process`), not only the root work directory. `KeyboardInterrupt` and `SystemExit` are control-flow signals: Stage hooks may perform best-effort cleanup, but these signals are never converted into retryable Stage failures.

All subprocess stdout collection is bounded in both normal and watchdog modes, so a noisy external command cannot grow Runner memory without limit.

## Reliability verification
For release/24H confidence, run the deterministic test suite first, then the opt-in live gate. `tool/workflow_dryrun.py --matrix` verifies happy/recovery paths and fail-closed behavior for unrecovered FAIL / technical ERROR. `tool/qwen_live_reliability.py` adds real Qwen process restart, deterministic expired-session -> Fresh Session recovery, HTTP 429/502/503 and three-minute disconnect recovery, timeout/session recovery, YAML List resume with per-item runtime options, Final AI fresh-session voting, detached-UI `stop.request -> exit 130 -> --resume`, and an opt-in single-process YAML endurance burst. The Windows 0.5H/24H presets run 4/8 sequential YAML items in one CLI process to complement the wall-clock soak. A 24H claim still requires the full requested wall-clock soak and a passing `summary.json`; preflight/burst probes alone are not a 24H claim.

## Planning bounded discovery and loop recovery

Planning now treats discovery as a bounded activity rather than a prerequisite for every task. Self-contained/greenfield work may plan immediately; existing-code work starts from the smallest goal-relevant entry point and expands only from concrete evidence. A confirmed missing file/symbol is not searched repeatedly without new evidence.

For backend loop signals such as `consecutive_identical_tool_calls` or `turn_tool_call_cap`, Planning gets at most one same-session retry. If the same loop class repeats, Runner rotates that Planning Stage to a fresh session while preserving durable workflow state. Dynamic backend turn/context text is normalized so the escalation counter cannot be reset by noisy stderr. This policy is intentionally Planning-specific; normal task/review retry semantics are unchanged.

Validation coverage: unit tests lock the retry sequence (`initial -> same -> fresh`), prompt-contract tests lock bounded discovery, `workflow_dryrun.py --matrix` continues to validate deterministic workflow routing/recovery, and `qwen_live_reliability.py` includes the loop classification/recovery policy preflight before live probes.

### Current unattended-safety notes

- Read-only Planning/Review/AI validation reuse one cached project baseline instead of copying the full project before every read-only stage. Legitimate writes incrementally update that baseline; unexpected read-only mutations are still restored.
- Windows core runtime/state/resource I/O uses extended-length paths internally. The live reliability preflight exercises >300-character runtime paths plus >260-character read-only restore paths before any model soak begins.
- The Web UI uses independent launch, Studio-edit, Builder, runtime, chat, and project locks. A slow Builder validation no longer serializes unrelated project launch/runtime operations.
- Non-loopback Web UI binding is rejected unless `--allow-remote` is explicitly supplied. The UI has no authentication layer, so remote exposure should remain exceptional.
- CLI Runtime status in the browser is static between polling fetches; no spinner/pulse is used to imply activity that has not actually been fetched.

