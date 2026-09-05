# State and Events

Version: 1.2.61

## State
Runner state lives under the project-relative work directory (default `.ai-task-runner`). It records run/cycle identity, current task index, task status/attempts/review information, session identifiers, progress/recovery metadata, and completion state needed for resume. The exact JSON is an internal persistence format; integrations should prefer the public API/events instead of editing state directly.

Detached local UI code may read a small stable subset of `state.json` for display (for example run id, current stage/task/progress/completion/error timestamps), but it must treat the file as read-only and tolerate additional internal fields. Do not couple UI behavior to the full persistence schema.

## Resume rules
`--resume` loads compatible state. A valid project `state.json` is authoritative; the temp backup is only restored when that primary state is missing or invalid, so an older backup cannot roll back a newer atomic primary write. Because a process restart destroys local `AIClient` objects, this is the only path that may reconstruct a new client from a saved remote session id. Within one running process, continuation always reuses the existing client/session. `--force-new` starts a new run. Script items use independent nested state directories. Executor session ids are preserved across completed TODOs and reused for the next TODO when usable. They are cleared only for explicit rebuild/completion conditions; project files and Runner state remain the durable source of truth.

## JSON events
With `--json-events`, progress is emitted as JSON Lines. Core events include schema/runner version, timestamp, status/detail, run id, cycle, current index, completed flag, and task summaries. Script mode also emits `script.item_started`, `script.item_completed`, and `script.item_failed`.

## Human UI
Human output is a rendering of the same state/event information. Multiline backend detail is normalized to one line only for the terminal; raw diagnostics keep the original content.

### Detached runtime visibility
`stream.log` is the local detached-UI surface for live output. It contains only the most recent bounded subprocess stdout, is cleared when a new subprocess starts, and is continuously refreshed while output arrives. It is intentionally disposable: it is not resume state, not an event history, and not an execution-control channel. `log.txt` / `debug/` provide history and diagnostics when needed.

`runner-process.json` is a small detached-UI runtime identity marker owned by the top-level Supervisor. It stores `supervisor_pid`, the current `worker_pid`, `started_at`, `project_root`, and `work_dir`; worker restart updates `worker_pid`, and normal Supervisor exit removes the marker. The existing `active-process` marker remains Runner-internal child/orphan cleanup state. PID metadata is never Workflow state and must not drive PASS/FAIL, retry, session, routing, or resume decisions. `stop.request` is the only file-based runtime control contract: its presence asks the top-level Supervisor to stop the current Worker and owned child process, consume the request, and exit 130. A stale request is cleared before a new Supervisor run. Resume and rerun are new launches (`--resume` / `--force-new`), not control files.

## State ownership
AI agents must not edit Runner state. The project policy file is automatically protected; Runner-managed debug/state mutations are owned by the Runner and are excluded from normal project-change semantics.

## Runtime scope
Each `execute()` call owns a scoped runtime/event context. YAML List child items temporarily replace that context and restore the parent on exit, so repeated programmatic calls and nested batch execution do not leak hooks/events/state across runs.
