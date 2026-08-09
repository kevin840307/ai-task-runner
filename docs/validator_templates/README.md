# Validator Interface and Templates

Version: 1.1.1

Use the shared local `validator_interface.py` pattern for deterministic example/smoke validators. Keep project-specific checks in the validator itself; the interface only standardizes report/error/warning/final exit behavior.

Runner invokes a file validator with `--project-root <root> --state-file <state>` followed by every repeatable `--validator-arg` exactly as provided. Validators may add their own argparse options (for example `--fab`) without requiring Runner changes.

A good validator checks observable requirements, uses deterministic local operations, produces actionable failures, and does not alter answer fixtures to pass. It should not assert the number/title of Planner TODOs unless planning behavior is the explicit subject of that smoke test.
## Diagnostic quality

Keep failures close to the operation that caused them. For generated JSON or CLI JSON output, use `parse_json(text, label)` so empty or malformed output becomes an actionable validation failure instead of an `E999` crash. After mutating commands, validate the resulting observable state immediately when practical; report the command/step plus expected and actual values. Unexpected validator exceptions include a short traceback, but normal project failures should use `AssertionError`/`ValidatorReport.error` with deterministic evidence rather than relying on crashes. Do not include implementation-specific answers in the fix text.

