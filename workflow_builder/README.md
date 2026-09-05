# Workflow Builder

External integration surface for creating a validated AI Task Runner Workflow through the system `workflow_builder.yaml` Workflow.

The caller supplies requirements and final output locations. The builder writes into an isolated draft folder under the selected project's `.ai-task-runner/workflow-builder/`, runs `workflow_builder/validation.py` (which checks generated files and calls the real `tool/workflow_dryrun.py`), and publishes to the requested location only after validation succeeds.

```bash
python workflow_builder/run.py \
  --project-root /path/to/project \
  --request-file request.md \
  --output-workflow /path/to/output/my.workflow.yaml \
  --output-prompt-dir /path/to/output/prompts
```

UI, CLI wrappers, or other local integrations can call the same script; no Runner import is required by the caller.
