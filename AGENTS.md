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

- Default: `--review-error-retries 1`. Review is best-effort: an explicit FAIL retries the TODO, while one Review call/format error provisionally accepts it with `review_skipped=true`; the final Validator remains authoritative.
- Strict: add `--strict-review`. Review errors never skip a TODO. Every error batch rebuilds only the Review session and retries without rerunning the successful executor.
- No project changes: Review is skipped immediately and the final Validator decides.

State records `review_skipped`, `review_skip_reason`, `review_error_attempts`, and `review_session_rebuilds` for audit and repair planning.

Final AI validation may run multiple independent fresh sessions. Respect `final_ai_validations` and `final_ai_required_passes`: errors abstain, explicit FAIL vetoes, and PASS must reach quorum. Final AI must inspect concrete high-impact safety and regression defects in addition to the stated goal.

## Executor scope isolation

TODO execution receives only the current task, relevant feedback, and concise constraints shared by every planned task. Do not reintroduce the complete goal or later TODO list into the Executor prompt; Planning and Final AI own whole-goal reasoning. Initial planning requires at least six concrete TODOs and one independent simple Judge acceptance. Split by independently actionable changes even when tasks share a file; Judge rejection is semantic and must not use title-keyword checks. Changed files accumulate across attempts, so Review can inspect prior saved work before another full execution attempt.

## Review Scope Isolation

Per-task Review uses a fresh independent session, is read-only, inspects the current TODO's changed files first, and reads only minimal additional evidence. Incomplete later TODOs or remaining whole-project work cannot block the current TODO or appear in `missing_items`. Final AI Validation independently judges the whole project.
