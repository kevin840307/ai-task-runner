# Workflow Dry Run Example

This folder validates real `workflow.yaml` routing without calling a real AI agent.
The tool reuses the production workflow loader, Pipeline, StageResult, and Stage finish and result reducers. Only Stage execution results are mocked.

Run on Windows:

```bat
run_dryrun.bat
```

The batch validates both:

1. `runner/workflow/system/mixed.yaml` with Plan -> generated Execute/Review, Review recovery, File Validator recovery, and final completion.
2. `dryrunexample/workflow.yaml`, a custom workflow where `check` fails three times, exercises `recover` and `repeat`, then still reaches final completion.

Scenario rules are test data only; they do not change production workflow behavior. Unspecified stages default to `PASS`. When a result sequence is exhausted, its last result repeats.

## Auto failure matrix

```bat
python ..\tool\workflow_dryrun.py ..\runner\workflow\system\mixed.yaml --matrix
```

The matrix automatically runs the happy path and one `FAIL -> recover -> closure` path for each recoverable Stage. Workflow syntax/options are always validated by the production loader/schema first. Invalid options fail with exit code `2` and `DRYRUN_ERROR`.
