# AI Task Runner Rules

AI Task Runner v1.1.1 is a small orchestration tool. It runs an external coding agent, keeps task state, retries failures, reviews each task, and runs final validation.

Follow these project rules:
- Keep changes small, maintainable, and generic. Do not hardcode smoke-case answers into runner logic.
- The runner owns task order, retry state, review state, and `.ai-task-runner/state.json`.
- Agents being executed by the runner write task deliverables; runner code only orchestrates, monitors, retries, reviews, and validates.
- Use `ai_task_runner.py` or `runner.api` as the public entry points.
- For tests, run focused pytest targets first, then `python -m pytest` before finalizing broad changes.
- Read `docs/PROJECT_GUIDE.md` for project structure and the 24h execution model.

## Review error policy

The normal flow remains `TODO execution -> AI Review -> final Validator`. A parsed Review FAIL is never skipped: its `missing_items` return to the same TODO. Only Review call, timeout, loop, parse, or schema errors use this policy.

- Default: `--review-error-retries 3`. After that many consecutive Review errors, a successful executor result with project file changes is provisionally accepted with `review_skipped=true`; the final Validator remains authoritative.
- Strict: add `--strict-review`. Review errors never skip a TODO. Every error batch rebuilds only the Review session and retries without rerunning the successful executor.
- No project changes: Review errors are never skipped, even in default mode.

State records `review_skipped`, `review_skip_reason`, `review_error_attempts`, and `review_session_rebuilds` for audit and repair planning.
