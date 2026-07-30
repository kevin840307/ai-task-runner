# Small-Model Endurance Case: Worklog Queue

Build a maintainable, standard-library-only Python command-line application named
`worklog`. This is intentionally a medium-sized integrated change. First inspect
the project, then split the work into small, independently implementable and
verifiable Tasks. Preserve the requirement IDs (`R01` through `R18`) in Task
descriptions or acceptance criteria so the saved plan can be audited.

Do not solve the entire specification in one Task. Do not create tiny mechanical
Tasks such as "create one file" unless that file is an independently verifiable
component. Prefer a small vertical slice or one coherent behavior per Task.

The validator is authoritative. Do not edit `validator.py`, `audit_plan.py`, `CASE_README.md`, the launcher
scripts, or files under `.ai-task-runner/validator-reports`.

## Product

The application manages a durable local work queue. It must run on Windows and
Linux with Python 3.10+ and must use only the Python standard library.

All commands use this form:

```text
python worklog.py --root <workspace> <command> [options]
```

Successful commands write exactly one JSON value to stdout. Failures write one
JSON error object to stderr and return the required nonzero exit code. Paths may
be absolute or relative.

## Requirements

### R01 — Maintainable package structure

Create these public implementation files:

```text
worklog.py
taskflow/__init__.py
taskflow/model.py
taskflow/storage.py
taskflow/service.py
taskflow/cli.py
```

Keep responsibilities separated: data normalization in `model`, durable files in
`storage`, state transitions in `service`, argument/output handling in `cli`, and
a thin `worklog.py` entry point. Do not hide the implementation in generated
code or additional executable scripts.

### R02 — State model and deterministic IDs

Store state under `<workspace>/.worklog/state.json` with schema version `1`, a
monotonic `next_id`, and a task collection. IDs must be allocated as `T0001`,
`T0002`, and so on without reuse. Every task exposes at least:

```text
id, title, status, priority, tags, depends_on, attempts, max_retries,
created_at, updated_at, last_error
```

Allowed priorities are `low`, `normal`, `high`, and `critical`. Normalize tags by
trimming whitespace, removing empty entries and duplicates, then sorting them.

### R03 — Durable and recoverable storage

Mutating commands must write state atomically and keep
`<workspace>/.worklog/state.json.bak` as a valid copy of the latest committed
state. If `state.json` is missing or invalid but the backup is valid, the next
command must restore and use the backup automatically. If neither file is valid,
return exit code `3` with error code `STORAGE_CORRUPT`.

### R04 — Initialize a workspace

`init` creates the `.worklog` directory, a valid empty state, its backup, and an
empty event log. Calling `init` again must be safe and must not erase existing
tasks.

### R05 — Add tasks

`add` requires `--title` and supports repeated `--tag`, repeated `--depends-on`,
`--priority` (default `normal`), and `--max-retries` (default `0`). Dependencies
must refer to existing tasks, cannot refer to the new task, and cannot contain
duplicates. Return the complete created task object.

### R06 — Show and list tasks

`show <task-id>` returns one task. `list` returns a JSON array. Unknown task IDs
return exit code `2` with error code `TASK_NOT_FOUND`.

### R07 — Filtering and deterministic ordering

`list` supports optional `--status`, `--priority`, and `--tag` filters that may be
combined. Results must be ordered by priority (`critical`, `high`, `normal`,
`low`), then creation time, then ID.

### R08 — Dependency-aware claiming

`claim <task-id>` moves a `pending` task to `running` and increments `attempts`.
Every dependency must already be `completed`. Otherwise return exit code `2`
with error code `DEPENDENCY_BLOCKED` and leave the state unchanged.

### R09 — Complete and fail transitions

`complete <task-id>` only accepts a `running` task and moves it to `completed`.
`fail <task-id> --reason <text>` only accepts a `running` task, moves it to
`failed`, and stores the reason in `last_error`. Invalid transitions return exit
code `2` with error code `INVALID_TRANSITION` without changing the task.

### R10 — Retry policy

`retry <task-id>` only accepts a `failed` task. It returns the task to `pending`
when another claim is allowed. The total allowed claims are
`1 + max_retries`. Once `attempts >= 1 + max_retries`, return exit code `2` with
error code `RETRY_EXHAUSTED` and leave the task failed.

### R11 — Update metadata

`update <task-id>` supports optional `--title`, `--priority`, repeated
`--add-tag`, and repeated `--remove-tag`. At least one change is required.
Normalization and validation must match `add`. Updating metadata must not change
status, attempts, dependencies, ID, or creation time.

### R12 — Cancel tasks

`cancel <task-id>` moves `pending`, `running`, or `failed` tasks to `cancelled`.
Completed and already-cancelled tasks reject the operation with
`INVALID_TRANSITION`.

### R13 — Import and export

`export --format json|csv --output <path>` exports every task in deterministic
list order. JSON export is an array of complete task objects. CSV must contain a
header and one row per task; serialize tags and dependencies as semicolon-joined
values.

`import --input <path>` accepts a JSON array. Each item requires `title` and may
contain `priority`, `tags`, and `max_retries`. Imported tasks receive fresh local
IDs and have no dependencies. Validate the whole input before committing so an
invalid item imports nothing. Return the created task array.

### R14 — Statistics

`stats` returns exactly this JSON shape (additional fields are allowed):

```json
{"total": 0, "status": {}, "priority": {}, "ready": 0}
```

`status` contains counts for `pending`, `running`, `completed`, `failed`, and
`cancelled`. `priority` contains counts for `low`, `normal`, `high`, and
`critical`. `ready` counts pending tasks whose dependencies are all completed.

### R15 — Append-only event history

Every successful mutation after initialization appends one JSON object to
`<workspace>/.worklog/events.jsonl`. Events have a strictly increasing integer
`seq`, UTC timestamp, action, task ID when applicable, and a compact details
object. Existing event lines must never be rewritten or renumbered.

### R16 — Stable CLI and error contract

Success returns `0`. User input, missing task, dependency, retry, and transition
errors return `2`. Unrecoverable storage errors return `3`.

Errors use this shape on stderr:

```json
{"ok": false, "error": {"code": "CODE", "message": "human readable"}}
```

Do not print tracebacks for expected errors. Unknown commands and malformed
arguments may use argparse's standard exit code, but must not corrupt storage.

### R17 — Automated tests

Add standard-library `unittest` coverage under `tests/`. Cover model
normalization, storage recovery, state transitions, dependency behavior, retry
limits, filtering, import atomicity, export, stats, and at least one CLI error.
The following command must pass:

```text
python -m unittest discover -s tests -v
```

### R18 — Documentation and maintainability

Write `README.md` with installation requirements, package responsibilities,
state files, command examples, transition rules, retry semantics, recovery
behavior, and test instructions. Keep each implementation file at or below 400
physical lines. Avoid duplicated transition logic and sample-specific answers.

## Completion criteria

The implementation is complete only when:

1. all requirements R01–R18 are represented in the saved plan;
2. the full validator passes without modifying the validator;
3. the project's own unit tests pass;
4. all state-changing behavior is implemented through the service/storage
   layers rather than duplicated in CLI handlers;
5. documentation describes the actual implementation.

Do not ask questions. Inspect the existing project and make reasonable,
portable choices where implementation details are not otherwise specified.
