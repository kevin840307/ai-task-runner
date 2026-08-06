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

- Review is one independent best-effort call. An explicit FAIL retries the TODO; a Review call/format error records `review_skipped=true` and continues to the final Validator.
- No project changes: Review is skipped immediately and the final Validator decides.

State records `review_skipped` and `review_skip_reason` for audit and repair planning.

For Final AI validation, each configured validation is an independent new session. Validate the current project directly; do not rely on prior verdicts. Report only evidence-backed blocking requirement, safety, destructive, security, reliability, portability, or regression defects.

## Planning isolation

Planning uses a fresh draft session, a different fresh refiner session, and one fresh no-tool Plan Judge pass. The Judges return only accepted/issues and check semantics rather than title keywords. Only a Judge-accepted plan is persisted. Initial planning requires at least six concrete TODOs; repair planning may contain fewer. Split by independently actionable changes, even when several TODOs modify the same file.

## Executor scope isolation

During TODO execution, treat only the current TODO as executable. The complete goal is intentionally not repeated because small models may attempt the entire project. Do not use the managed original-requirement reference to discover additional work; inspect only directly relevant project files. Goal-wide constraints are carried through acceptance criteria shared by every planned task. Repeated failures with accumulated saved changes are reviewed before another full attempt.

## Review Scope Isolation

Per-task Review uses a fresh independent session, is read-only, inspects this TODO's accumulated changed files first, and reads only minimal additional evidence. Incomplete later TODOs or remaining whole-project work cannot block the current TODO or appear in `missing_items`. Final AI Validation independently judges the whole project.
