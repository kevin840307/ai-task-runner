# Local UI

A small GPT-style local UI for AI Task Runner.

```bash
python ui/main.py
```

## Scope

This UI is intentionally isolated from the Runner implementation:

- UI has its own `main()` and does not import `runner.*`.
- One project maps to one persistent conversation.
- UI reads Runner-owned runtime files and launches the existing CLI as a detached process.
- Runner/Core files are not modified by UI development unless explicitly called out.

## Main surfaces

The UI intentionally keeps four small user-facing areas:

- **Projects** — open/recent project folders.
- **Task conversation** — one persistent task history per project, runtime status and Live Output. The current UI intentionally does not provide a general-purpose Chat mode.
- **Workflow Studio** — CRUD/edit Workflow YAML and Stage/Skill Prompt files, validate before publish/save, import/export, and AI-assisted Workflow generation.
- **Runtime controls** — Run / Stop / Continue / Reset(New Task) / Rerun.

Thinking/Reasoning panels, multi-session navigation, Run Center, patch review, assets, analytics and other platform-oriented surfaces are intentionally omitted.

## Runtime contract

The UI reads:

- `.ai-task-runner/state.json` — current durable workflow status.
- `.ai-task-runner/runner-process.json` — current supervisor/worker PID marker.
- `.ai-task-runner/stream.log` — current bounded subprocess output.
- `.ai-task-runner/debug/last-result.txt` — best available completed model result for the first UI version.

The UI writes only UI/control files:

- `.ai-task-runner/stop.request` — request the Supervisor to stop.
- `.ai-task-runner/ui/messages.jsonl` — UI-owned persistent conversation.
- `.ai-task-runner/ui/chat-state.json` — UI-owned run-id completion deduplication.
- `.ai-task-runner/ui/requests/<request-id>/prompt.md` — immutable user goal snapshot for a new Run/Rerun.
- `.ai-task-runner/ui/requests/<request-id>/request.json` — UI-owned input manifest (workflow/backend and optional Python validator path).

A normal Send launches the existing CLI with `--goal-file <.../prompt.md>` instead of putting a long goal on the command line. If the selected Workflow contains a file-validation Command that uses `{validator}`, the composer shows a **Python validation** path and the CLI receives `--validator <path>`. If the selected Workflow does not use Python validation, that field is hidden and no validator argument is sent. AI validation does **not** create a separate request prompt file: `ai_validator` is a normal Workflow Stage whose Prompt lives in Workflow/Prompt configuration.

Runtime lifecycle stays explicit:

- **Stop** writes `.ai-task-runner/stop.request`; Supervisor owns shutdown and child cleanup.
- **Continue** launches the existing CLI with `--resume`.
- **Reset** removes Runner-owned runtime artifacts but preserves `.ai-task-runner/ui/` task history and request snapshots.
- **Completed -> next Run** automatically resets old Runner runtime state before creating the next request.
- **Stopped/Interrupted -> new Run** is blocked until the user chooses Continue or Reset, so resumable work is never silently discarded.
- **Rerun** creates a fresh immutable `prompt.md` snapshot and starts a new run after resetting old runtime state.

On Windows, UI-launched Runner/Workflow Builder subprocesses use hidden-console creation flags; opening the browser UI does not flash a CMD window.

## Workflow Studio

Workflow Studio remains file based and does not import Runner workflow code.

It presents assets in three groups:

- **System** — `runner/workflow/system/*.yaml|yml`, `runner/prompts/system/**/*.md`, and built-in `runner/prompts/stages/**/*.md`; visible/validatable/exportable but immutable and undeletable.
- **Custom** — `runner/workflow/custom/*.yaml|yml` and `runner/prompts/custom/**/*.md`; user-editable shared assets. `skill_prompt_review_chain.yaml` and its related Prompts live here.
- **Project** — selected-project top-level `.ai-task-runner.yaml` / `*workflow*.yaml|yml` and `prompts/**/*.md`; user-editable project-local assets.

Custom is a real repository location rather than a UI-only label. New/imported assets can target Custom or Project. Workflow/Prompt export produces a small JSON package; import validates syntax and Workflow Prompt references before creating a new file and never overwrites an existing asset. Prompt deletion is rejected while any known Workflow Stage still resolves to that Prompt.

Safety rules:

1. **Any tracked running project locks all Workflow/Prompt editing.** Shared workflows/prompts may be used by multiple projects, so the first version uses a conservative global UI lock.
2. The lock is checked again server-side at Save time, not only in the browser.
3. Stale/dead PID markers do not lock editing.
4. Files are saved with temporary-file + `os.replace` atomic replacement.
5. Every edit uses a SHA-256 expected hash. If another UI tab/editor changed the file, Save is rejected and the user must Reload.
6. Server-side path containment prevents crafted requests from editing unrelated YAML/Markdown files.
7. Workflow Validate invokes the existing `tool/workflow_dryrun.py --matrix --json --max-steps 500`; it can validate the current unsaved YAML or Visual-flow draft without writing the Workflow first. Stage Editor also has **Validate Draft** for unsaved Stage/Flow-field changes. Save still runs the same gate again before commit.
8. Unsaved editor changes trigger confirmation before switching project/view/file or closing the page.

The global edit lock only knows projects tracked by this UI. A CLI run in a completely unknown/untracked project cannot be discovered without adding a Core/global runtime registry, which is intentionally outside the current UI-only boundary.

## AI workflow generation

Workflow Studio's **Generate with AI** is wired to the real external `workflow_builder/` integration surface. The UI launches `workflow_builder/run.py`, which runs the System `runner/workflow/system/workflow_builder.yaml` Workflow with `runner/prompts/system/workflow_builder.md` and `workflow_builder/validation.py`. Generated files first live in an isolated draft under the selected Project's `.ai-task-runner/workflow-builder/`; the validator checks required files/Prompt references and runs the real `tool/workflow_dryrun.py --matrix --json --max-steps 500`. Only a passing draft is published to the selected Custom or Project destination. Existing output files are never overwritten by default.

The same builder can be invoked outside the UI:

```bash
python workflow_builder/run.py --project-root <project> --request-file request.md --output-workflow runner/workflow/custom/generated.workflow.yaml --output-prompt-dir runner/prompts/custom
```

## Task completion

When `state.json` reports a completed run, the UI reads `debug/last-result.txt` and appends one assistant result message. The run id is persisted in `chat-state.json`, so polling, reopening the UI, or repeated reads do not duplicate that result.

`last-result.txt` is currently the best available result without changing Core. It is not promoted to a new Runner public contract by this UI.

## Live output

There is no Thinking/Reasoning panel. Structured `reasoning`, `thinking`, `analysis`, and `chain_of_thought` fields/types are filtered from display. Normal work text such as `Running static analysis` remains visible.

## Runtime states

The UI presents:

- `Running` when the supervisor PID is alive.
- `Interrupted` when a runtime marker is stale and durable state is resumable.
- `Failed` when durable state contains an error.
- `Completed` when durable state is complete.
- `Idle` otherwise.

Missing project paths remain visible in the sidebar as `Missing` so they can be removed without silently losing UI history.

## Explicit Workflow AI validator

An `ai_validator` that appears in an explicitly selected Workflow is enabled by Stage presence and uses its normal Stage Prompt. No extra UI-generated AI-validation prompt file is created. Legacy/default Workflow selection keeps its existing validator gate.

## Tests

Run UI tests with:

```bash
python -m pytest ui/tests -q
```

The tests cover project persistence, missing paths, stale PID handling, completion deduplication, live-output filtering, detached CLI launch modes, Stop/Resume/Rerun behavior, no-Runner-import boundary, Workflow Studio edit locking, atomic/hash guarded saves, path containment and dry-run validation.

## Layout and Workflow Studio

The UI follows the supplied `static` interaction model instead of inventing a separate dashboard layout:

- The task history owns the full workspace height. `header / summary / history` are the grid rows; the GPT-style composer floats above the bottom edge. History extends behind it and reserves bottom scroll space equal to the measured composer height, so reaching the bottom leaves usable blank space instead of hiding messages behind the composer. The message textarea stays at a fixed height and scrolls internally.
- Projects are rendered top-down immediately below the Projects heading; only the project list scrolls.
- The composer contains a real Workflow picker. Its entries come from the file-based Workflow catalog and the selected path is passed to the existing CLI `--workflow` option.
- Workflow Studio is a normal workspace page, not a modal. It has **Visual** and **YAML** modes plus a persistent **Workflow / Prompt** source switch in both modes.
- **Workflow + Visual** follows the static Designer interaction: Stage cards are draggable; **single click selects**, **double click edits**, and the selected Stage gets a bottom-right floating action bar for Edit / Move Up / Move Down / Remove.
- **Prompt** uses one first-class Prompt Editor in both Visual and YAML modes. Prompt Markdown is never edited inside the Stage modal.
- The Prompt Editor exposes insertable `{{tag}}` chips. The UI derives the available tags from the current Runner prompt-context source with AST parsing, so it does not import `runner.*` or advertise unsupported parameters. Prompt saves also run Jinja syntax/unknown-variable checks.
- Stage Editor keeps only useful tabs: **Settings / Control**. It exposes one **Prompt** selector for prompt-backed Stages. For a reused Stage, Flow-invocation `prompt` / `status` overrides are shown before Stage defaults, so the editor displays and writes the value that invocation actually uses. `continuation_prompt` remains supported by Core/YAML for same-session optimization but is intentionally not duplicated in the common Visual editor. Plan/Command do not show a misleading Prompt field.
- Stage settings cover the current semantic Stage contract, including parser, retry (`-1` supported), type-specific command/plan/AI-validator settings, and Flow-invocation routing (`scope`, `label`, `restart_at`, `repeat`, `fresh_after_same_failures`).
- Workflow YAML editing has line numbers, Tab/Shift+Tab indentation, Enter auto-indent, Ctrl/Cmd+S, and live YAML syntax location feedback.
- **New Workflow / New Prompt** create editable Project or Custom assets, never overwriting an existing file. System assets are never mutated or deleted.
- Add Stage, New Workflow and Open Project use static-style dialogs instead of browser `prompt()` dialogs. Modal headers/footers remain visible while only the body scrolls on short viewports.
- Workflow/Prompt file navigation and the right-side Steps/Prompt editor fill the remaining Studio height. `studioFileList` keeps a stable vertical scrollbar gutter, and the right editor surface ends on the same bottom baseline as the left Studio sidebar; only inner lists/editors scroll.
- Visual flow saves replace only the top-level `flow:` block. Stage-field edits patch only the affected Stage fields so anchors, merge keys, unrelated comments, and formatting outside the edited field remain intact. Stage removal from Flow always uses the reusable confirmation dialog.
- Add Stage, Workflow Save and Workflow Import validate Prompt references before writing. A base Stage requires an explicit Prompt; explicit Prompt paths must resolve to an existing Prompt. Prompt deletion checks all known Workflow usages first.
- Workflow/Stage draft Validate uses the reusable top-center auto-dismiss toast: green on PASS and red on FAIL. Validation does not write the draft; Save re-validates before commit. The same short-lived action feedback is reused for Save, Add/Remove Stage, create/import/export/delete, Run/Stop/Continue/Rerun/Reset, and Project add/remove. Persistent decisions such as delete confirmation, unsaved-change confirmation, edit locks, and detailed validation errors remain in their existing modal/banner/output surfaces.
- Runtime edit guard, stale-PID handling, hash conflict detection, path containment, and atomic file writes apply to Visual, YAML, Stage, Workflow and Prompt editing.

## Static-aligned interaction contract

- Workflow Studio itself is a page/workspace; **only Stage editing is a modal**.
- Stage Editor selects Prompt references; Prompt content belongs to the shared Prompt workspace/editor.
- Visual and YAML modes both expose the same Workflow / Prompt source navigation. Prompt uses the same editor regardless of the selected mode.
- UI runtime code does not import `runner.*`; it uses the existing filesystem/subprocess adapter only.
- If any tracked Project has a live Runtime, all Workflow/Prompt mutation controls become read-only and the server repeats the same guard on write.

## QA evidence shipped with the UI

The delivery includes current Chromium evidence under `ui/qa_evidence/`:

- `QA_REPORT.md` — measured contracts, automated test commands, and lifecycle/workflow safety checks.
- `browser_metrics.json` — numeric layout/interaction measurements.
- `screenshots/01_task_layout.png` — task composer / Project layout.
- `screenshots/02_workflow_dropdown.png` — unclipped body-level Workflow picker.
- `screenshots/03_workflow_studio_system_custom.png` — System / Custom / Project asset groups.
- `screenshots/04_stage_selected_actions.png` — selected Stage and floating actions.
- `screenshots/05_stage_editor_modal.png` — Stage Editor modal.
- `screenshots/06_ai_workflow_builder.png` — AI Workflow Builder modal.
- `screenshots/07_import_asset_modal.png` — bounded Import Workflow/Prompt modal.
- `screenshots/08_prompt_editor.png` — Prompt workspace/editor.
- `screenshots/09_add_project_modal.png` — Add Project dialog.
- `screenshots/10_prompt_alignment.png` — Prompt Editor/sidebar bottom alignment.
- `screenshots/11_stage_prompt_override.png` — reused Stage shows the selected Flow invocation's actual Prompt/Status.
- `screenshots/12_stage_validation_success_toast.png` — unsaved Stage draft validation PASS toast.
- `screenshots/13_stage_validation_error_toast.png` — unsaved Stage draft validation FAIL toast.

These files are evidence only and are never read by Runner or UI runtime.
