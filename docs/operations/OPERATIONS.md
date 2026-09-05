# Operations and Troubleshooting

Version: 1.2.61

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
