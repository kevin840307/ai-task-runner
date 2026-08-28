# Regression Workflow Demo (Runner 1.2.43+)

Runnable six-action regression workflow: Project Discovery → Documentation → E2E SPEC → Verification Design → Regression DSL → Execution & Qualification, with Review/Grill recovery gates and a final 5-agent fresh-session vote (3 PASS required).

The example intentionally makes the first documentation Grill fail. `fix.md` must receive bounded `previous.data`, repair the gap, and return to the same Grill session. Review/Grill continuation prompts send only the new target/evidence after their full contract has already been seen in that session.

Run deterministic mock verification from the repository root:

`examples\11_regression_workflow_demo\run_test.bat`

Run the workflow with the mock agent and keep the generated project state:

`examples\11_regression_workflow_demo\run_mock.bat`

Run with real Qwen:

`examples\11_regression_workflow_demo\run_qwen.bat`

All BAT launchers (`run_example`, `run_qwen`, `run_mock`, `run_test`) execute from a fresh temporary repository copy and print the retained workspace path for debugging.

## Grill scope

This is a small demo. Grill-AI checks only the explicit required items for project documentation and E2E specification. It must not expand scope into optional production/enterprise topics or fail on minor wording/style improvements.

