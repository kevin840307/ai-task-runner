# Workflow Dry Run Example

This folder validates the production Workflow graph without calling a real AI agent.

`tool/workflow_dryrun.py` reuses the real Workflow loader and FlowEngine. Only Stage execution results are mocked, so Dry Run does not maintain a second routing/recovery engine.

Run on Windows:

```bat
run_dryrun.bat
```

The batch covers:

1. `runner/workflows/mixed.yaml` with explicit Planning -> task-scoped Execute/Review -> File/AI validation.
2. `dryrunexample/workflow.yaml` with an ordinary FAIL result edge back to an earlier Stage.
3. Automatic deterministic failure matrices for both.

Scenario data changes only mocked Stage results. Unspecified Stages default to PASS; when a configured sequence is exhausted, its last value repeats.

## Auto failure matrix

```bat
python ..\tool\workflow_dryrun.py ..\runner\workflows\mixed.yaml --matrix --json
```

The matrix checks happy-path closure, reachable semantic FAIL routes and safe ERROR stop behavior. Workflow syntax and route targets are always validated by the production loader first.

Technical retry, Same Session, Fresh Session and API backoff are intentionally not modeled here. Those belong to StageExecutor tests and the real-Qwen reliability harness.
