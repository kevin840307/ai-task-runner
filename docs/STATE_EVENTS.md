# State and Events

Version: 1.2.1

## State
Runner state lives under the project-relative work directory (default `.ai-task-runner`). It records run/cycle identity, current task index, task status/attempts/review information, session identifiers, progress/recovery metadata, and completion state needed for resume. The exact JSON is an internal persistence format; integrations should prefer the public API/events instead of editing state directly.

## Resume rules
`--resume` loads compatible state. Because a process restart destroys local `AgentClient` objects, this is the only path that may reconstruct a new client from a saved remote session id. Within one running process, continuation always reuses the existing client/session. `--force-new` starts a new run. Script items use independent nested state directories. Executor session ids are preserved across completed TODOs and reused for the next TODO when usable. They are cleared only for explicit rebuild/completion conditions; project files and Runner state remain the durable source of truth.

## JSON events
With `--json-events`, progress is emitted as JSON Lines. Core events include schema/runner version, timestamp, status/detail, run id, cycle, current index, completed flag, and task summaries. Script mode also emits `script.item_started`, `script.item_completed`, and `script.item_failed`.

## Human UI
Human output is a rendering of the same state/event information. Multiline backend detail is normalized to one line only for the terminal; raw diagnostics keep the original content.

## State ownership
AI agents must not edit Runner state. The project policy file is automatically protected; Runner-managed debug/state mutations are owned by the Runner and are excluded from normal project-change semantics.
