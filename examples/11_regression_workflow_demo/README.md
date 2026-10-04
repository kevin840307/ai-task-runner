# Regression Workflow Demo

Runnable regression workflow built only from the current Stage contract:

- AI work uses `type: base, profile: execute`.
- Review gates use `type: base, profile: review` and explicit `routes.fail` rollback.
- Challenge reviews use `session_policy: fresh` for independent evidence checks.
- Final validation uses `type: ai_validator`, five Fresh Session runs, and requires three PASS results.

There is no Repair/Grill/Fix runtime, `repeat` graph control, or legacy `type: task/review` Stage. A failed Review or Challenge Review simply follows its configured semantic FAIL edge back to the Stage that should improve the work.

Run deterministic mock verification from the repository root:

`examples\11_regression_workflow_demo\run_test.bat`

Run the workflow with the mock agent and retain the generated project state:

`examples\11_regression_workflow_demo\run_mock.bat`

Run with real Qwen:

`examples\11_regression_workflow_demo\run_qwen.bat`

All launchers run from a fresh temporary repository copy and print the retained workspace path for debugging.

The challenge-review prompts deliberately stay scoped to the demo's required documentation and E2E behaviors; they must not expand the task into unrelated production concerns.
