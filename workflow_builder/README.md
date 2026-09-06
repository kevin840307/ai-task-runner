# Workflow Builder

`workflow_builder/` is the external integration surface for generating validated AI Task Runner Workflow packages without importing or modifying Runner Core.

Canonical Builder assets live together here:

- `workflow_builder.yaml` — Builder Workflow.
- `prompt.md` — Builder Skill/Prompt.
- `validation.py` — validates generated files and runs the real Workflow dry-run matrix.
- `run.py` — generate a draft and optionally publish it.
- `publish.py` — publish an already validated draft.

`runner/workflow/system/workflow_builder.yaml` remains only as a compatibility mirror for the existing `SYSTEM_WORKFLOWS["workflow_builder"]` registry. It points to `workflow_builder/prompt.md`. No Runner Python code is changed for this relocation.

## CLI: generate and publish

```bash
python workflow_builder/run.py \
  --project-root /tmp/workflow-builder-workspace \
  --request-file request.md \
  --output-workflow /path/to/output/my.workflow.yaml \
  --output-prompt-dir /path/to/output/prompts
```

`--project-root` is the Runner's filesystem workspace. External callers may intentionally point it at a real project when project inspection is desired, but the UI always supplies its own isolated temporary Builder job instead.

## Draft-only mode

The UI does **not** use the currently selected user Project as the Builder root. It creates an isolated UI-owned job workspace and passes that temporary directory to the Runner as its technical `--project-root`:

```text
ui/data/workflow-builder/<job-id>/
├─ .ai-task-runner/       # isolated Builder runtime only
├─ draft/
├─ status.json
└─ result.json
```

This means Workflow generation works even when no Project has been opened or registered in the UI. The Runner still needs a filesystem `--project-root` internally, but for UI generation that root is the temporary Builder job itself, never the current user Project.

Draft-only mode creates and validates files only under the job directory. It does **not** create a Custom or Project Workflow. The UI opens a dedicated Generator page, asks only for Prompt + Backend, shows status-only feedback while this command runs, and then reviews the temporary draft through Visual/YAML/Prompt views. Every Generate uses a new job directory. Cancel requests stop the Builder Runner and discard the temporary job. Regenerate discards the old draft and starts a new job on the next Generate. Only the explicit **Save Workflow** action invokes `publish.py`; the Save dialog supplies the final name/destination and the current edited draft is revalidated immediately before publication. **Custom** can be saved without any open Project. **Current Project** becomes available only when a Project is actually open at Save time.
