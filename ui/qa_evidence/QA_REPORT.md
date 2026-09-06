# UI / Workflow QA Evidence

This folder contains browser screenshots and the measured layout contract used for the current delivery.
The evidence is not read by Runner or UI runtime code.

## Browser checks

Chromium was rendered at 1440×900 plus narrow/short viewport checks. The measured values are in `browser_metrics.json`.

Verified contracts:

- Task composer reaches the viewport bottom with a 0 px bottom gap.
- Workflow dropdown is rendered through a `BODY` portal and remains inside the viewport instead of being clipped by the floating composer.
- Workflow Studio shows **System / Custom / Project** groups.
- System assets are read-only; Custom and Project assets are editable when no tracked Runtime is active.
- Stage single click selects; double click opens Stage Editor.
- Selected Stage floating actions remain anchored while the action panel opens above them.
- Stage Status is used as the visible title when present and is constrained to one-line ellipsis. Flow-invocation Status overrides take precedence over shared Stage defaults.
- Legacy Round evidence included the earlier Workflow Builder modal; Round 17 replaces generation with the dedicated Generator page.
- Import Workflow/Prompt modal stays inside the viewport and the custom Choose file control is visible.
- Prompt Editor and the left Studio sidebar end on the same bottom baseline: `prompt_bottom_gap = 0`.
- `studioFileList` keeps `overflow-y: scroll` and `scrollbar-gutter: stable`.
- Add Project modal renders inside the viewport.
- Reused Stage Prompt/Status overrides were opened in Chromium: `custom/design.md` and `Designing solution` matched the actual Flow invocation.
- Unsaved Stage draft Validate produced a green PASS toast and a red FAIL toast without browser page errors.
- Runtime card consumes the same semantic CLI snapshot as `LiveUI`: Cycle/Progress, `[x] / [>] / [ ]` Plan TODO rows, status and detail.
- Plan-produced TODOs are visible in the browser as soon as durable `state.json` contains them; stale/missing console snapshots fall back to the same marker rules.
- Running feedback is visible both in history and in the floating composer: CLI spinner and Run button frame change locally every 120 ms, the composer pulses, and the active Project dot pulses.
- Project rows show explicit `RUN / IDLE / DONE / INT / STOP / MISS` status labels; the status list refreshes independently every 1.5 s.
- Remove Project confirmation is a full-viewport layer at z-index 7000, above the composer (z-index 90) and portal menus; its backdrop covers the composer.
- Browser page errors: 0 for the recorded QA run.

## Screenshots

1. `screenshots/01_task_layout.png` — Workflow task composer / project layout.
2. `screenshots/02_workflow_dropdown.png` — unclipped body-level Workflow picker.
3. `screenshots/03_workflow_studio_system_custom.png` — System / Custom / Project asset groups.
4. `screenshots/04_stage_selected_actions.png` — selected Stage and floating actions.
5. `screenshots/05_stage_editor_modal.png` — Stage Editor modal.
6. `screenshots/06_ai_workflow_builder.png` — historical pre-Round-17 Builder modal evidence (superseded by screenshots 29–34).
7. `screenshots/07_import_asset_modal.png` — bounded Import Workflow/Prompt modal.
8. `screenshots/08_prompt_editor.png` — Prompt workspace/editor.
9. `screenshots/09_add_project_modal.png` — Add Project dialog.
10. `screenshots/10_prompt_alignment.png` — Prompt Editor and Studio sidebar bottom alignment.
11. `screenshots/11_stage_prompt_override.png` — Stage Editor showing the actual Flow-level Prompt/Status override.
12. `screenshots/12_stage_validation_success_toast.png` — Stage draft validation PASS.
13. `screenshots/13_stage_validation_error_toast.png` — Stage draft validation FAIL.
14. `screenshots/14_cli_runtime_todos_running.png` — CLI-synced Runtime view with Plan TODOs, RUN/IDLE/DONE Project state and animated Running composer.
15. `screenshots/15_remove_project_overlay_fixed.png` — Remove Project backdrop covers the runtime view and floating composer.

`browser_metrics_round10.json` records the latest runtime/TODO/status/overlay measurements.


### Latest Chromium runtime / Prompt measurements

```text
Runtime card background              white
Runtime output background            white
Runtime title frame 1                - AI 正在處理目前任務
Runtime title frame 2                \ AI 正在處理目前任務
Runtime status animates in card      true
Input height                         60 px
Input placeholder while Running      描述要完成的功能或修復內容...
Run visible while Running            false
Stop visible while Running           true
Project row height                   42 px
Options position                     absolute popover
Composer height before Options       166 px
Composer height after Options        166 px
Stopped Continue visible             true
Stopped Reset visible                true
Stopped Run visible                  false
System rules.md Prompt badge         Prompt valid
System rules.md tags                 project / project.root / plugin_rules
Prompt explicit Validate button      Validate Prompt
Browser page errors                  0
```

The previous `Prompt warning` on `runner/prompts/system/rules.md` and `structured_output_retry.md` was a false positive in the UI validator, not a broken Runner Prompt. Those two System templates are rendered by `runner/prompts/loader.py` with dedicated variables (`plugin_rules` and `error`) rather than the normal Stage prompt context. Workflow Studio now statically derives those dedicated contracts from literal `render_prompt(...)` calls, so the tags and validation match the actual Runner path without importing Runner Core. A repository scan validates all 24 current Prompt files with 0 warnings.

## Automated tests executed before packaging

```text
python -m pytest ui/tests -q
140 passed

python -m pytest tests/test_prompt_resources.py tests/test_prompt_contracts.py tests/test_console_snapshot.py tests/test_terminal_ui_single_line.py tests/test_runtime_controls.py -q
28 passed

python -m pytest \
  tests/test_workflow_yaml.py \
  tests/test_prompt_resources.py \
  tests/test_prompt_contracts.py \
  tests/test_workflow_builder.py \
  tests/test_workflow_dryrun_tool.py \
  tests/test_live_reliability_tool.py -q
126 passed

python -m pytest \
  tests/test_architecture.py \
  tests/test_architecture_layout.py \
  tests/test_documentation.py \
  tests/test_resources.py \
  tests/test_runtime_controls.py \
  tests/test_worker_supervisor.py \
  tests/test_runtime_hardening.py \
  tests/test_ui_extension_boundary.py \
  tests/test_source_bundle_cleanup.py \
  tests/test_recovery_policy.py \
  tests/test_flow_graph.py \
  tests/test_stage_executor.py \
  tests/test_stage_capabilities.py \
  tests/test_stage_specialization.py \
  tests/test_declarative_stage.py -q
132 passed
```

Additional Stage/flow unit files were run individually and passed. A monolithic `pytest tests` run was also attempted, but the repository contains deliberately long mock/integration paths; the command exceeded the execution window rather than producing a failing assertion. The targeted suites above cover the files/contracts changed in this delivery.

Static checks:

```text
node --check ui/static/app.js
PASS

python -m compileall -q ai_task_runner.py runner ui workflow_builder tool
PASS
```

## Runtime / task lifecycle checked by automated tests

- UI-launched Runner / Workflow Builder uses hidden-console creation flags on Windows.
- Running → Stop.
- Stopped / Interrupted → Continue (`--resume`) or Reset.
- Completed → next task resets Runner-owned runtime artifacts while preserving `.ai-task-runner/ui/` history and request snapshots.
- A new task creates an immutable UI request `prompt.md`; optional Python validation is passed only when the selected Workflow requires it.
- AI validation remains a normal Workflow Stage using its Stage Prompt; no separate UI-generated AI validation prompt is created.

## Workflow safety checked by automated tests

- Top-level linear `task` / `review` profiles are supported without pending TODO state when custom Prompts drive a global SOP. This preserves the Plan/TODO reducer when tasks exist while allowing `runner/workflow/custom/skill_prompt_review_chain.yaml` and `examples/workflow_multi_prompt.yaml` to close without a synthetic Plan Stage.
- `workflow_dryrun_preflight()` now includes the Custom linear skill/prompt chain before live-Qwen probes.
- Formal Workflow matrix dry-run results for this delivery: system file 3/3, system ai 3/3, system mixed 4/4, system workflow_builder 2/2, custom skill_prompt_review_chain 2/2, custom_workflow_latest 2/2, workflow_multi_prompt 1/1, regression workflow demo 5/5.

- `builtin` was migrated to `system`; old source-path references are rejected by migration scans.
- Shared editable assets live in `runner/workflow/custom/` and `runner/prompts/custom/`.
- `skill_prompt_review_chain.yaml` and its related prompts are classified as Custom.
- System assets cannot be edited or deleted through UI APIs.
- Workflow saves/imports/new Stage changes validate Prompt references and run Workflow dry-run closure checks before the write is committed.
- Prompt deletion is blocked while a known Workflow Stage references it.
- Prompt Validate is a first-class Studio action. Prompt Save and Prompt Import use the same server-side Jinja/variable contract gate and cannot write until validation passes.
- Special System Prompt contracts are discovered from `runner/prompts/loader.py`; `system/rules.md` accepts `project.root` + `plugin_rules`, and `system/structured_output_retry.md` accepts `error`, eliminating the prior false warning without widening normal Stage Prompt tags.
- AI Workflow Builder drafts are validated with `workflow_builder/validation.py` and `tool/workflow_dryrun.py --matrix --json --max-steps 500` before publish.

## Draft validation + action toast contract

- Workflow **Validate** runs against the current unsaved editor draft. YAML mode sends the current YAML text; Visual mode sends the current flow ordering/removals and validates a temporary composed Workflow. Stage Editor **Validate Draft** does the same for unsaved Stage fields plus Flow invocation fields. The real Workflow file is not modified by either validation action.
- Validation PASS uses the existing top-center green auto-dismiss toast. Validation FAIL uses the same component in red; long details remain in the Stage/Workflow status or validation output so the toast stays compact.
- Workflow/Prompt Save still re-runs its validation gate before writing, so editing after a successful Validate cannot bypass validation.
- Short action feedback also uses the reusable toast for Save, Add Stage, create/import/export, task Run/Stop/Continue/Rerun/Reset, and Project add/remove. Confirmation dialogs, unsaved-change prompts, edit locks, and long error details remain persistent rather than auto-dismissing.

## Custom skill/prompt status contract

`runner/workflow/custom/skill_prompt_review_chain.yaml` now gives the shared Stage definitions generic status values and each Flow invocation a more specific status (Designing, Reviewing design, Implementing, Reviewing implementation, Updating documentation, Reviewing documentation). Validation recovery steps also have explicit status. This keeps runtime/UI progress meaningful while still reusing only three Stage definitions.

## Round 12 screenshots

- `screenshots/16_white_runtime_stop_in_run_slot.png` — white live Runtime conversation card; Stop replaces Run in the same composer action slot.
- `screenshots/17_options_popover.png` — Options opens as a floating popover with no composer-height change.
- `screenshots/18_stopped_continue_reset.png` — stopped incomplete task shows Continue + Reset in the Run action area.
- `screenshots/19_prompt_loader_contract_valid.png` — System rules Prompt uses its dedicated tags and shows Prompt valid / Validate Prompt.

## Conversation visibility regression (Round 13)

The user-reported missing-conversation case was reproduced with a long previous Assistant result, a new User requirement, a Running Runtime card, and the floating composer. The cause was twofold: the history did not automatically follow a newly appended Runtime card, and flexbox was allowed to shrink the Runtime card to roughly 1–2 px when prior history was tall.

The final contract now verifies:

- `#messages.history > .message` and `.live-activity` use `flex: 0 0 auto`; conversation cards cannot collapse when history overflows.
- A newly created Running Runtime card is forced into view below the latest User requirement.
- Runtime updates stay pinned only while the user is following the bottom.
- Manual upward scrolling is preserved and is not overridden by the 750 ms runtime poll.
- Completion removes the Runtime card and follows the final Assistant conversation into view.
- Browser page errors: 0.

Evidence:

- `screenshots/20_runtime_conversation_visible.png` — long prior history + current User + fully visible Running Runtime card.
- `screenshots/21_completed_assistant_conversation.png` — Runtime card removed after completion and final Assistant conversation visible.
- `browser_metrics_round13.json` — measured scroll/runtime/completion contract.

## Round 15 — remembered Run options / scalable dropdowns / multi-project status

Chromium QA additionally verifies:

- Browser preferences restore the last Project plus per-Project Backend / Workflow / per-Workflow Python validator path.
- Backend uses the same custom menu style as Workflow and opens upward through a body-level portal.
- Backend and Workflow menus become scrollable when the option count exceeds five visible rows.
- Round 15 verified spinner isolation. Round 16 tightens the header further: Runtime conversation title is the lifecycle status (`Running / Stopped / Interrupted`); Stage `status` stays in the CLI/runtime body and summary instead of becoming the bubble title.
- A 60-TODO Runtime card has no nested output scrollbar (`max-height: none`, `overflow: visible`); the outer conversation history owns scrolling and TODO 60 remains reachable.
- Project rows use equal 4 px left/right list gutters when the list does not need a scrollbar.
- Two tracked projects can both render `RUN` simultaneously.

Measured values are in `browser_metrics_round15.json`; screenshots 22–24 cover the long TODO list, Backend popup, and Workflow five-row scroll behavior.

## Round 16 — external Builder Draft / styled Stage discard / lifecycle bubble title

Chromium QA verifies:

- The Runtime bubble title is `Running` while the detailed Stage status (`AI 正在執行最終驗證` in the fixture) remains visible in the runtime body.
- Workflow Builder canonical assets are `workflow_builder/workflow_builder.yaml` + `workflow_builder/prompt.md`; no Runner Python source change is required. `runner/workflow/system/workflow_builder.yaml` remains only as the compatibility registry mirror.
- Generate with AI is now a two-step creation contract: **Generate Draft -> validation -> preview -> explicit Save Workflow**. During generation only status/spinner is shown and the modal cannot be closed.
- A validated Draft is labeled `DRAFT · NOT SAVED`; it is not present in Custom/Project Studio files until Save. Discard deletes the temporary job directory.
- Generated Workflow YAML and Prompt files are previewed before Save.
- Closing a dirty Stage Editor uses the reusable styled `Discard Stage changes?` confirmation instead of browser `window.confirm`.
- Browser page errors: 0.

Evidence:

- `screenshots/25_runtime_title_running.png`
- `screenshots/26_builder_running_status_only.png`
- `screenshots/27_builder_draft_preview_not_saved.png`
- `screenshots/28_stage_discard_styled_confirm.png`
- `browser_metrics_round16.json`

## Round 17 — dedicated Workflow Generator page / fresh-job Draft review

The Workflow Builder UI is now page based rather than a large generation modal. Chromium QA verifies the exact requested lifecycle:

1. Clicking **Generate with AI** hides the normal Workflow Studio editor and opens `workflowGeneratorPage`.
2. The input page asks only for **Prompt + Backend**. Workflow name/destination are not visible at this stage.
3. **Generate** creates a new job and moves to a status-only waiting screen. The form and Draft review are hidden while generation runs.
4. A successful result opens **DRAFT · NOT SAVED** review with Visual / YAML / Prompt tabs. The Workflow file list remains unchanged until Save.
5. YAML and Prompt edits mark the temporary Draft dirty. **Validate Draft** validates the current edited files and clears the dirty marker only on PASS.
6. **Save Workflow** opens a small modal; only here are Workflow name + Custom/Project destination requested. `Validate & Save` is the publication boundary.
7. **Regenerate** discards the current Draft, returns to the original Prompt, and the next Generate receives a different job id/new AI run.
8. **Cancel Generation** uses the reusable confirmation, moves through cancelling, removes the temporary job, and returns to Workflow Studio.
9. Opening Generate with AI again after cancel/discard starts clean: Prompt blank, no job id, no resumed Draft.
10. The 390×844 check has no horizontal document overflow. Browser page errors: 0.

Measured values are in `browser_metrics_round17.json`.

Evidence:

- `screenshots/29_generator_input_page.png` — dedicated Prompt + Backend input page; Name/Destination are intentionally absent.
- `screenshots/30_generator_status_only.png` — centered spinner + generation status + Cancel Generation only.
- `screenshots/31_generator_review_draft.png` — validated `DRAFT · NOT SAVED` Visual review; no asset has been created yet.
- `screenshots/32_generator_review_editable.png` — temporary YAML/Prompt review/edit surface.
- `screenshots/33_generator_save_modal.png` — compact Save dialog where Name/Destination finally appear.
- `screenshots/34_generator_mobile_input.png` — narrow viewport containment check.


## Round 18 — Project-independent Workflow Generator workspace

Workflow generation no longer depends on an open/selected Project. Chromium UI (mocked Builder API) plus unit/static/API regression verifies:

- **Generate with AI** can open and start generation with zero registered Projects.
- Builder jobs live under `ui/data/workflow-builder/<job-id>/`; the job itself is passed as the isolated Runner `--project-root`. No user Project path is passed to Generate/Status/Validate/Cancel/Discard.
- Cancel writes stop state only into the isolated Builder runtime and cannot stop a user Project runtime.
- Draft validation is Project-independent.
- Saving to **Custom** works with no Project. **Current Project** is disabled in the Save dialog unless a Project is actually open.
- Draft generation/validation may continue while a tracked Project Runtime is active; final publication still obeys the Studio edit guard.

Evidence:

- `screenshots/35_generator_no_project_required.png` — zero Project entries, generated Draft review, and Save dialog defaulting to Custom with Current Project disabled.
- `browser_metrics_round18.json` — confirms no `project` field is posted to Generate and no `project=` query is used by status polling.

## Round 19 — resumable singleton Workflow Generator + visible temporary workspace

Automated UI/API regression verifies the Generator lifecycle is now owned by the UI server rather than the browser tab:

- `ui/data/workflow-builder/active.json` points to exactly one active Generator job.
- Closing/reloading the browser does not cancel a queued/running job. On the next UI load, `/api/studio/generate/active` restores the same job id, request, Backend, status, and workspace.
- A ready but unsaved Draft is also restored; a failed job remains visible until the user retries/discards it.
- A second Generate request cannot create another job while `active.json` owns an existing job; the API returns the existing job instead.
- Cancel -> cancelled -> discard, explicit Discard, and successful Save remove the temporary job and clear the active registry.
- The input page shows the temporary workspace pattern before Generate. Generating and Review states show the exact `ui/data/workflow-builder/<job-id>` path.
- Running/ready Generator state alone no longer triggers `beforeunload`; only genuinely unsaved browser-side edits do. This permits close/reopen without silently cancelling the Builder.
- Generator restoration forces the Workflow view visible even when the UI initially opens on Tasks.

Regression coverage for this round is in `ui/tests/test_ui.py` and `ui/tests/test_static_contract.py`. No new browser screenshot is claimed for this round; the behavior is covered by server-state and static UI contract tests.


## Round 20 — Generator layout / editable Draft / Studio restore

The user-reported Generator input overlap was reproduced from the supplied 1548×812 screenshot. The input page previously constrained the Prompt card inside a fixed grid while helper text, temporary path, and actions occupied implicit rows; the large `height:100%` textarea could overflow into those rows. The final layout uses a normal column flow with a bounded/resizable Prompt area, a dedicated metadata block, wrapping temporary path, and an internally scrollable Generator main surface.

Verified contracts:

- Prompt textarea no longer overlaps the explanatory text or temporary workspace row.
- Temporary workspace paths wrap instead of colliding with labels/actions.
- Generator actions stay reachable; narrow viewports scroll the Generator main surface rather than clipping content.
- Successful results are explicitly **EDITABLE**. **Edit YAML** and **Edit Prompt** expose the existing temporary editors; edits mark the Draft dirty and require validation before Save. Visual remains a validated preview and is refreshed after **Validate Draft**.
- Returning from a ready Draft via Cancel/Discard re-renders the cached Workflow catalog immediately and calls `refreshStudioFiles()` before the user continues, fixing the empty Workflow list that previously recovered only after a browser refresh. The same restore path is used after generation cancellation and unsent-request exit.
- Static/API UI regression: 148 UI tests PASS.
- Browser layout measurement at 1548×812: Prompt bottom 462.55 px; helper top 519.73 px; workspace top 547.73 px; actions bottom 628.58 px; no overlaps.
- 390×844 containment: document width remains 390 px and Generator main becomes vertically scrollable when required.

Evidence:

- `screenshots/36_generator_layout_fixed.png` — corrected desktop input layout.
- `screenshots/37_generator_editable_draft.png` — explicit editable Draft review UI.
- `screenshots/39_generator_mobile_layout_fixed.png` — narrow layout remains contained and vertically scrollable.
- `browser_metrics_round21.json` — measured non-overlap and edit-affordance contract.


## Round 22 — Studio CRUD completeness / shared dialog architecture

The Studio CRUD follow-up closes the remaining first-version UX gaps without changing Runner Core:

- Workflow/Prompt unsaved navigation now uses the shared styled dialog instead of native `window.confirm`.
- Workflow and Prompt asset menus expose **Rename** and **Duplicate**. System assets stay immutable but may be duplicated to Custom; referenced Prompt rename remains blocked.
- Stage removal offers a deliberate choice between **Remove from Flow** and **Delete Stage definition**. Definition deletion is blocked when other Flow/recovery/routing references still use the Stage.
- Workflow/Prompt catalogs include client-side search/filter and clear action.
- Shared UI helpers were split into `ui/static/js/ui-dialogs.js` and `ui/static/js/studio-support.js` so confirmation/input-dialog behavior and small catalog helpers do not keep expanding the main `app.js`.
- `ui/tests/test_browser_crud_e2e.py` covers one end-to-end CRUD journey through the production browser UI.
- UI regression: 155 tests PASS, including the browser CRUD journey.

Evidence:

- `screenshots/40_studio_search_crud_actions.png` — search plus Rename/Duplicate asset actions.
- `screenshots/41_stage_delete_definition_choice.png` — Flow-only removal versus guarded definition deletion.
- `screenshots/42_styled_unsaved_dialog.png` — shared styled unsaved-changes confirmation.
