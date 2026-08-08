# Validator Interface and Templates

Version: 1.1.1

Use the shared local `validator_interface.py` pattern for deterministic example/smoke validators. Keep project-specific checks in the validator itself; the interface only standardizes report/error/warning/final exit behavior.

Runner invokes a file validator with `--project-root <root> --state-file <state>` followed by every repeatable `--validator-arg` exactly as provided. Validators may add their own argparse options (for example `--fab`) without requiring Runner changes.

A good validator checks observable requirements, uses deterministic local operations, produces actionable failures, and does not alter answer fixtures to pass. It should not assert the number/title of Planner TODOs unless planning behavior is the explicit subject of that smoke test.
