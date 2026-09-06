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

- `.ai-task-runner/state.json` — current durable workflow status and Plan-produced TODO list.
- `.ai-task-runner/console-view.json` — Runner-owned semantic CLI snapshot written by `ConsoleObserver`; it uses the same `LiveUI` status/detail, cycle/progress and `[x] / [>] / [ ]` TODO markers as the CLI.
- `.ai-task-runner/runner-process.json` — current supervisor/worker PID marker.
- `.ai-task-runner/stream.log` — current bounded subprocess output retained for debugging/compatibility.
- `.ai-task-runner/debug/last-result.txt` — best available completed model result for the first UI version.

The browser does not recreate a separate runtime vocabulary. It renders `console-view.json` directly and falls back to `state.json` with the same CLI marker rules if the snapshot is briefly missing/stale. As soon as Plan persists TODOs, those TODO rows therefore appear in the UI. The spinner token is animated locally in the browser so the Runner does not need to rewrite a file every 120 ms.

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
8. Unsaved editor changes trigger the shared styled confirmation dialog before switching project/view/file or closing the page; Workflow/Prompt no longer fall back to native `window.confirm`.
9. Workflow/Prompt assets expose a compact asset menu with **Rename** and **Duplicate**. Rename stays in the same editable scope and is blocked for referenced Prompts; System assets remain immutable but can be duplicated into Custom.
10. Visual Stage removal distinguishes **Remove from Flow** from **Delete Stage definition**. Definition deletion is server-validated and blocked while another Flow/recovery/routing reference still targets that Stage.
11. The Studio catalog has a client-side search/filter across the active Workflow/Prompt source without adding a server dependency.
12. `ui/tests/test_browser_crud_e2e.py` exercises the production browser journey across Prompt/Workflow create, edit, validation, Stage manipulation, rename/duplicate/search, reference-safe deletion, reload, and cleanup.

The global edit lock only knows projects tracked by this UI. A CLI run in a completely unknown/untracked project cannot be discovered without adding a Core/global runtime registry, which is intentionally outside the current UI-only boundary.

## AI workflow generation

Workflow Studio's **Generate with AI** is wired to the external `workflow_builder/` integration surface. The canonical Builder Workflow and Skill live together at `workflow_builder/workflow_builder.yaml` and `workflow_builder/prompt.md`; `workflow_builder/validation.py` runs the real `tool/workflow_dryrun.py --matrix --json --max-steps 500`. `runner/workflow/system/workflow_builder.yaml` is retained only as a compatibility mirror for the unchanged Runner named-workflow registry.

The browser flow is intentionally draft-first and page based rather than a large modal:

1. **Generate with AI** opens a dedicated Generator page. If there is no active Generator job, the input page starts blank. If a job already exists, the UI reopens that exact job instead of creating another one.
2. The input step asks only for **Prompt + Backend**. Workflow name and Custom/Project destination are not requested yet. The page also shows the temporary workspace pattern before generation.
3. **Generate** creates the single active UI-owned job under `ui/data/workflow-builder/<job-id>/` and writes `ui/data/workflow-builder/active.json`. It uses Builder `--draft-only` mode and does not use or require the selected Project. The job directory itself is the isolated Runner `--project-root`. The waiting page shows only spinner + generation status plus the exact temporary workspace path; YAML, Prompts, TODOs and Agent output are intentionally hidden.
4. Closing or refreshing the browser does **not** cancel generation. On the next UI load, `GET /api/studio/generate/active` restores the same queued/running/cancelling job, or the same ready/failed result. Exactly one Generator job may be active at a time across tabs/windows.
5. **Cancel Generation** uses a styled confirmation, requests Runner stop, waits for the Builder to become cancelled, removes the temporary job, clears `active.json`, and returns to Workflow Studio.
6. A successful run opens the **DRAFT · NOT SAVED** review page. The exact temporary workspace path remains visible. The result is explicitly marked **EDITABLE**: Visual remains the validated preview, while **Edit YAML** and **Edit Prompt** are direct temporary editors. Modified drafts are marked validation-dirty; **Validate Draft** validates the exact current temporary files and refreshes the Visual preview.
7. **Regenerate** discards the current draft (thereby releasing the active job), returns to the same Prompt for adjustment, and the next Generate creates a new job/new AI run.
8. **Save Workflow** is the only point that opens a small modal for **Workflow name + destination**. `Custom` is always available, including when no Project exists. `Current Project` is enabled only if a Project is open at Save time. `Validate & Save` revalidates the current YAML/Prompts, publishes atomically, removes the temporary job, and clears `active.json`. Until that succeeds, the draft never appears in System/Custom/Project asset lists.
9. **Discard/Back** asks before throwing away a ready draft or unsent request. Returning from Cancel/Discard immediately re-renders the cached Workflow catalog and refreshes it from the server, so the normal Workflow list/editor is restored without a browser refresh. Draft generation and Draft validation remain usable while another Project Runtime is active because they touch only the isolated UI workspace; publication still obeys the normal Studio edit guard.

The same builder can be invoked outside the UI:

```bash
python workflow_builder/run.py --project-root <builder-workspace> --request-file request.md --output-workflow runner/workflow/custom/generated.workflow.yaml --output-prompt-dir runner/prompts/custom
```

## Task completion

When `state.json` reports a completed run, the UI reads `debug/last-result.txt` and appends one assistant result message. The run id is persisted in `chat-state.json`, so polling, reopening the UI, or repeated reads do not duplicate that result.

`last-result.txt` is currently the best available result without changing Core. It is not promoted to a new Runner public contract by this UI.

## Live runtime / CLI view

There is no Thinking/Reasoning panel. The main runtime surface mirrors the CLI semantic display: Cycle/Progress, Plan TODO rows, current status and detail. Structured `reasoning`, `thinking`, `analysis`, and `chain_of_thought` fields/types are not promoted to this surface.

While a task is Running, runtime feedback stays in the conversation instead of the input box: the white CLI Runtime card updates its status/TODO lines and spinner from the same file-based CLI state, while the current Project dot pulses and is labeled `RUN`. The composer keeps its normal placeholder. The bottom-right Run action is replaced by Stop while Running, then by Continue + Reset when an incomplete task is stopped. Idle/Completed/Interrupted/Stopped Projects have explicit `IDLE / DONE / INT / STOP` labels.
Conversation entries are non-shrinking flex items. A long previous Assistant result therefore cannot collapse the newly appended Runtime card into a 1–2px line. The task history uses sticky-to-bottom behavior: new User/Runtime/Assistant entries follow the bottom while the user is already following the latest task, but manual upward scrolling disables auto-follow until the user returns to the bottom or starts a new task. A completed Runtime card is removed and the completed result is rendered as the normal Assistant conversation card.

## Runtime states

The UI presents:

- `Running` when the supervisor PID is alive.
- `Interrupted` when a runtime marker is stale and durable state is resumable.
- `Failed` when durable state contains an error.
- `Completed` when durable state is complete.
- `Idle` otherwise.

Missing project paths remain visible in the sidebar as `Missing` so they can be removed without silently losing UI history. The Project list also exposes live `RUN / IDLE / DONE / INT / STOP / MISS` badges and colored state dots; runtime status is polled independently from the selected Project.

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

- The task history owns the full workspace height. `header / summary / history` are the grid rows; the GPT-style composer floats above the bottom edge. History extends behind it and reserves bottom scroll space equal to the measured composer height, so reaching the bottom leaves usable blank space instead of hiding messages behind the composer. The message textarea is fixed at 60px and scrolls internally.
- Projects are rendered top-down immediately below the Projects heading, shifted slightly inward for clearer hierarchy; only the project list scrolls. Each row shows a live runtime badge/dot so running vs idle projects are visible without selecting them.
- The composer contains a real Workflow picker. Its entries come from the file-based Workflow catalog and the selected path is passed to the existing CLI `--workflow` option. Options opens as an absolute floating popover, so selecting backend/Rerun never changes composer or textarea height.
- Workflow Studio is a normal workspace page, not a modal. It has **Visual** and **YAML** modes plus a persistent **Workflow / Prompt** source switch in both modes.
- **Workflow + Visual** follows the static Designer interaction: Stage cards are draggable; **single click selects**, **double click edits**, and the selected Stage gets a bottom-right floating action bar for Edit / Move Up / Move Down / Remove.
- **Prompt** uses one first-class Prompt Editor in both Visual and YAML modes. Prompt Markdown is never edited inside the Stage modal.
- The Prompt Editor exposes insertable `{{tag}}` chips. Normal Stage Prompts derive tags from `runner/prompts/context.py`. Dedicated System templates such as `rules.md` and `structured_output_retry.md` derive their own variables statically from `runner/prompts/loader.py`, so `plugin_rules` / `error` are valid only where Runner really supplies them. Prompt Validate, Save, and Import all use the same Jinja/unknown-variable contract gate.
- Stage Editor keeps only useful tabs: **Settings / Control**. It exposes one **Prompt** selector for prompt-backed Stages. For a reused Stage, Flow-invocation `prompt` / `status` overrides are shown before Stage defaults, so the editor displays and writes the value that invocation actually uses. `continuation_prompt` remains supported by Core/YAML for same-session optimization but is intentionally not duplicated in the common Visual editor. Plan/Command do not show a misleading Prompt field.
- Stage settings cover the current semantic Stage contract, including parser, retry (`-1` supported), type-specific command/plan/AI-validator settings, and Flow-invocation routing (`scope`, `label`, `restart_at`, `repeat`, `fresh_after_same_failures`).
- Workflow YAML editing has line numbers, Tab/Shift+Tab indentation, Enter auto-indent, Ctrl/Cmd+S, and live YAML syntax location feedback.
- **New Workflow / New Prompt** create editable Project or Custom assets, never overwriting an existing file. System assets are never mutated or deleted.
- Add Stage, New Workflow and Open Project use static-style dialogs instead of browser `prompt()` dialogs. Modal headers/footers remain visible while only the body scrolls on short viewports.
- Workflow/Prompt file navigation and the right-side Steps/Prompt editor fill the remaining Studio height. `studioFileList` keeps a stable vertical scrollbar gutter, and the right editor surface ends on the same bottom baseline as the left Studio sidebar; only inner lists/editors scroll.
- Visual flow saves replace only the top-level `flow:` block. Stage-field edits patch only the affected Stage fields so anchors, merge keys, unrelated comments, and formatting outside the edited field remain intact. Stage removal from Flow always uses the reusable confirmation dialog.
- Add Stage, Workflow Save and Workflow Import validate Prompt references before writing. A base Stage requires an explicit Prompt; explicit Prompt paths must resolve to an existing Prompt. Prompt deletion checks all known Workflow usages first.
- Workflow/Stage/Prompt draft Validate uses the reusable top-center auto-dismiss toast: green on PASS and red on FAIL. Validation does not write the draft; Save re-validates before commit. Prompt Import also runs the same server-side Prompt gate before file creation. The same short-lived action feedback is reused for Save, Add/Remove Stage, create/import/export/delete, Run/Stop/Continue/Rerun/Reset, and Project add/remove. Persistent decisions such as delete confirmation, unsaved-change confirmation, edit locks, and detailed validation errors remain in their existing modal/banner/output surfaces.
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
- `screenshots/06_ai_workflow_builder.png` — historical pre-Round-17 Builder modal evidence (superseded by screenshots 29–34).
- `screenshots/07_import_asset_modal.png` — bounded Import Workflow/Prompt modal.
- `screenshots/08_prompt_editor.png` — Prompt workspace/editor.
- `screenshots/09_add_project_modal.png` — Add Project dialog.
- `screenshots/10_prompt_alignment.png` — Prompt Editor/sidebar bottom alignment.
- `screenshots/11_stage_prompt_override.png` — reused Stage shows the selected Flow invocation's actual Prompt/Status.
- `screenshots/12_stage_validation_success_toast.png` — unsaved Stage draft validation PASS toast.
- `screenshots/13_stage_validation_error_toast.png` — unsaved Stage draft validation FAIL toast.
- `screenshots/14_cli_runtime_todos_running.png` — earlier CLI/TODO mirror evidence.
- `screenshots/16_white_runtime_stop_in_run_slot.png` — current white Runtime conversation card and Stop replacing Run.
- `screenshots/17_options_popover.png` — floating Options popover without composer resize.
- `screenshots/18_stopped_continue_reset.png` — Continue + Reset after an incomplete Stop.
- `screenshots/19_prompt_loader_contract_valid.png` — dedicated System Prompt tags, Prompt valid, and Validate Prompt.
- `screenshots/25_runtime_title_running.png` — Runtime conversation title uses lifecycle status (`Running`) while the detailed Stage status remains in the body.
- `screenshots/26_builder_running_status_only.png` — Workflow Builder generation phase shows only status/spinner and blocks close until completion.
- `screenshots/27_builder_draft_preview_not_saved.png` — validated Workflow/Prompt Draft preview with explicit **Discard Draft / Save Workflow** actions; still not a Studio asset.
- `screenshots/28_stage_discard_styled_confirm.png` — reusable styled confirmation for unsaved Stage changes.
- `screenshots/29_generator_input_page.png` — dedicated Generate Workflow page; only Prompt + Backend are requested.
- `screenshots/30_generator_status_only.png` — stacked spinner/status-only waiting phase with Cancel Generation.
- `screenshots/31_generator_review_draft.png` — validated `DRAFT · NOT SAVED` Visual review page.
- `screenshots/32_generator_review_editable.png` — temporary YAML/Prompt edits before Save.
- `screenshots/33_generator_save_modal.png` — compact Save dialog where Name/Destination appear for the first time.
- `screenshots/34_generator_mobile_input.png` — narrow viewport containment check.
- `screenshots/36_generator_layout_fixed.png` — Generator Prompt / helper / temporary-path / actions no longer overlap at the reported desktop size.
- `screenshots/37_generator_editable_draft.png` — generated Draft is explicitly editable through Edit YAML / Edit Prompt before Save.
- `screenshots/38_generator_return_catalog_restored.png` — Discard returns to Workflow Studio with the Workflow catalog immediately restored.
- `screenshots/39_generator_mobile_layout_fixed.png` — narrow Generator input uses vertical scrolling instead of clipping/overlap.
- `browser_metrics_round21.json` — measured layout, edit affordance, and mocked-browser return-to-Studio restoration contract.
- `screenshots/15_remove_project_overlay_fixed.png` — Remove Project confirmation backdrop covers the floating composer and runtime surface.
- `browser_metrics_round17.json` — measured Generator page / fresh-job / cancel / review / Save contracts.

These files are evidence only and are never read by Runner or UI runtime.

## Remembered Run preferences

The browser keeps only stable UI selections in `localStorage` (`ai-task-runner.ui.preferences.v1`):

- last selected Project;
- Backend per Project;
- Workflow per Project;
- Python validator path per Project + Workflow.

Runtime lifecycle state, Options-open state and unsent task text are deliberately not persisted. Runtime truth still comes from each Project's `.ai-task-runner` files.

Backend choices are discovered by statically parsing `runner/backends/*.py` and `runner/config/defaults.py`; UI does not import Runner Core. Backend and Workflow use the same upward custom dropdown pattern. Menus cap at roughly five visible rows and scroll when more choices exist.

## Multiple Project runs

The UI/Runner contract permits separate Projects to run at the same time: each Project owns its own `.ai-task-runner` state/process marker and the UI launch lock is held only while spawning a child, not for the lifetime of the run. The Project rail polls every Project independently and can show multiple `RUN` labels. Workflow/Prompt Studio editing remains globally locked while any tracked Project is running. Actual inference concurrency/throughput still depends on the selected backend/server capacity.
