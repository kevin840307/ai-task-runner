# Operations

## Reliability ownership

StageExecutor owns technical retry/session recovery. FlowEngine owns semantic PASS/FAIL navigation. Operational debugging should first determine which side failed.

### Technical ERROR

Examples: timeout, backend crash, transient HTTP failure, malformed model transport/session failure.

Behavior:
1. retry the current Stage using its current Session when appropriate;
2. after repeated recoverable failures, rotate only that Stage to a fresh Session;
3. keep graph position unchanged;
4. stop fail-closed at the current Stage when a finite retry budget is exhausted.

`stage_retries=-1` means unlimited technical retry. HTTP 429/502/503 use delay/backoff controlled by retry delay/max-delay settings.

### Semantic FAIL

FAIL is a valid Stage result, not a technical exception. FlowEngine follows `routes.fail` or stops when no FAIL route exists. A route back to an earlier Stage is the rollback/loop.

There is no operational repair/recover Stage.

## Session operations

- `main`: primary Runner Session.
- `role`: durable Session owned by one Stage name.
- `fresh`: new Session every invocation.
- `auto`: built-in/internal profile behavior.

Resetting one failed `role` Session must not clear other role Sessions. Global session reset clears primary + durable role Sessions.

## Resume

Resume continues from committed state. Important durable fields include workflow/task position, previous transition evidence, primary Session and per-role Sessions.

A crash between Stage commits may repeat the current Stage; completed committed Stages must not repeat.

## Stop / detached UI

The UI writes the Runner control marker. Supervisor shutdown must clean process/control markers and child processes. Relaunch with `--resume` must use durable state rather than UI-local status.

## Logs and diagnostics

Collect:

- state.json;
- Runner events/log;
- runner-process/control markers when process ownership is involved;
- `stream.log` for live subprocess output;
- current/last prompt and result;
- relevant bounded debug history;
- exact command and visible error.

Logs must remain bounded/rotated for long unattended runs.

## Release gates

1. Ubuntu + Windows compile/pytest and Studio build.
2. deterministic dry-run/session/retry/resume matrix.
3. real-Qwen short gate:
   `tool\qwen_live_reliability_0_5h.bat`
4. high-density soak.
5. full 24H:
   `tool\qwen_live_reliability_24h.bat`

The real-Qwen gate covers Dynamic Handoff/session policies, Review/Validator rollback, transient HTTP, disconnect, expired Session, process restart, detached UI resume, YAML List resume, custom Task producer and final AI voting.

Do not claim a live/24H result only because the probe exists in source; keep the emitted summary/run directory as evidence.

## Change policy

After deterministic CI is green, do not perform speculative structural refactors before live/24H gates. Fix only reproducible/high-value failures that affect unattended operation, state correctness, session isolation, process cleanup or UI/runtime contract consistency.
