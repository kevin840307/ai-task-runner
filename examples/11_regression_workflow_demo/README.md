# Regression Workflow Demo (Runner 1.2.41+)

A small runnable example using only current Runner features. It keeps six action skills and shares Review, Grill, Fix, and Final Validation skills.

Session policy: Writer/Fix share the writer session; all Reviews share `review_client`; all Grills share `grill_client`; final validation uses five fresh sessions with a 3/5 threshold. `fix.md` consumes the bounded `previous.data` provided by Runner 1.2.41, so feedback is not duplicated in YAML or prompts.

Run from the repository root:

`examples\\10_regression_workflow_demo\\run_mock.bat`

For real Qwen:

`examples\\10_regression_workflow_demo\\run_qwen.bat`
