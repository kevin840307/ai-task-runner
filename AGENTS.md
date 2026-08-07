# AI Task Runner Rules

AI Task Runner v1.1.1 is a small orchestration tool. It runs an external coding agent, keeps task state, retries failures, reviews each task, and runs final validation.

Follow these project rules:
- Keep changes small, maintainable, and generic. Do not hardcode smoke-case answers into runner logic.
- The runner owns task order, retry state, review state, and `.ai-task-runner/state.json`.
- Project `.ai-task-runner.yaml` defines protected read-only paths; never run `git add`, `git commit`, or `git push`. Final Git acceptance is human review.
- Agents being executed by the runner write task deliverables; runner code only orchestrates, monitors, retries, reviews, and validates.
- Use `ai_task_runner.py` or `runner.api` as the public entry points.
- For tests, run focused pytest targets first, then `python -m pytest` before finalizing broad changes.
- Read `docs/PROJECT_GUIDE.md` for project structure and the 24h execution model.

## Review error policy

The normal flow remains `TODO execution -> AI Review -> final Validator`. A parsed Review FAIL is never skipped: its `missing_items` return to the same TODO. Only Review call, timeout, loop, parse, or schema errors use this policy.

- Review starts with one independent read-only call. An explicit FAIL retries the TODO. If Review errors with a resumable session, one same-session no-tool finalization is attempted; only another error records `review_skipped=true` and continues to the final Validator.
- No project changes: Review is skipped immediately and the final Validator decides.

State records `review_skipped` and `review_skip_reason` for audit and repair planning.

Final AI validation may run multiple independent fresh sessions. Respect `final_ai_validations` and `final_ai_required_passes`: errors abstain, explicit FAIL vetoes, and PASS must reach quorum. Final AI must inspect concrete high-impact safety and regression defects in addition to the stated goal.

## Executor scope isolation

TODO execution receives only the current task, relevant feedback, and concise constraints shared by every planned task. Do not reintroduce the complete goal or later TODO list into the Executor prompt; Planning and Final AI own whole-goal reasoning. Initial planning requires at least six concrete TODOs. The first draft Planner session performs bounded read-only map → select → focused deep read in a dedicated Understand turn, then always produces TODOs in a same-session no-tool Plan turn; if that session cannot be reused, fall back to fresh no-tool minimal planning without restarting exploration. Refiner and Judge are fresh soft quality gates: infrastructure/format errors keep the last usable plan, while explicit Judge rejection gets bounded rewrites before Final Validator owns correctness. Split by independently actionable changes even when tasks share a file; do not use title-keyword checks. Executor calls may stop after one coherent improvement. Preserve partial changes: a failed call with new project changes goes directly to Review; repeated matching fresh-session failures with no changes defer to final validation.

## Review Scope Isolation

Per-task Review uses a fresh independent session, is read-only, inspects the current TODO's changed files first, and reads only minimal additional evidence. Incomplete later TODOs or remaining whole-project work cannot block the current TODO or appear in `missing_items`. Final AI Validation independently judges the whole project.
