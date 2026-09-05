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
- AI Workflow Builder modal is wired and visible.
- Import Workflow/Prompt modal stays inside the viewport and the custom Choose file control is visible.
- Prompt Editor and the left Studio sidebar end on the same bottom baseline: `prompt_bottom_gap = 0`.
- `studioFileList` keeps `overflow-y: scroll` and `scrollbar-gutter: stable`.
- Add Project modal renders inside the viewport.
- Reused Stage Prompt/Status overrides were opened in Chromium: `custom/design.md` and `Designing solution` matched the actual Flow invocation.
- Unsaved Stage draft Validate produced a green PASS toast and a red FAIL toast without browser page errors.
- Browser page errors: 0 for the recorded QA run.

## Screenshots

1. `screenshots/01_task_layout.png` — Workflow task composer / project layout.
2. `screenshots/02_workflow_dropdown.png` — unclipped body-level Workflow picker.
3. `screenshots/03_workflow_studio_system_custom.png` — System / Custom / Project asset groups.
4. `screenshots/04_stage_selected_actions.png` — selected Stage and floating actions.
5. `screenshots/05_stage_editor_modal.png` — Stage Editor modal.
6. `screenshots/06_ai_workflow_builder.png` — Generate with AI / Workflow Builder modal.
7. `screenshots/07_import_asset_modal.png` — bounded Import Workflow/Prompt modal.
8. `screenshots/08_prompt_editor.png` — Prompt workspace/editor.
9. `screenshots/09_add_project_modal.png` — Add Project dialog.
10. `screenshots/10_prompt_alignment.png` — Prompt Editor and Studio sidebar bottom alignment.
11. `screenshots/11_stage_prompt_override.png` — Stage Editor showing the actual Flow-level Prompt/Status override.
12. `screenshots/12_stage_validation_success_toast.png` — Stage draft validation PASS.
13. `screenshots/13_stage_validation_error_toast.png` — Stage draft validation FAIL.

## Automated tests executed before packaging

```text
python -m pytest ui/tests -q
107 passed

python -m pytest \
  tests/test_workflow_yaml.py \
  tests/test_prompt_resources.py \
  tests/test_prompt_contracts.py \
  tests/test_workflow_builder.py \
  tests/test_workflow_dryrun_tool.py \
  tests/test_live_reliability_tool.py -q
123 passed

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
- AI Workflow Builder drafts are validated with `workflow_builder/validation.py` and `tool/workflow_dryrun.py --matrix --json --max-steps 500` before publish.

## Draft validation + action toast contract

- Workflow **Validate** runs against the current unsaved editor draft. YAML mode sends the current YAML text; Visual mode sends the current flow ordering/removals and validates a temporary composed Workflow. Stage Editor **Validate Draft** does the same for unsaved Stage fields plus Flow invocation fields. The real Workflow file is not modified by either validation action.
- Validation PASS uses the existing top-center green auto-dismiss toast. Validation FAIL uses the same component in red; long details remain in the Stage/Workflow status or validation output so the toast stays compact.
- Workflow/Prompt Save still re-runs its validation gate before writing, so editing after a successful Validate cannot bypass validation.
- Short action feedback also uses the reusable toast for Save, Add Stage, create/import/export, task Run/Stop/Continue/Rerun/Reset, and Project add/remove. Confirmation dialogs, unsaved-change prompts, edit locks, and long error details remain persistent rather than auto-dismissing.

## Custom skill/prompt status contract

`runner/workflow/custom/skill_prompt_review_chain.yaml` now gives the shared Stage definitions generic status values and each Flow invocation a more specific status (Designing, Reviewing design, Implementing, Reviewing implementation, Updating documentation, Reviewing documentation). Validation recovery steps also have explicit status. This keeps runtime/UI progress meaningful while still reusing only three Stage definitions.
