# AI Task Runner Rules

AI Task Runner v1.1.1 is a small orchestration tool. It runs an external coding agent, keeps task state, retries failures, reviews each task, and runs final validation.

Follow these project rules:
- Keep changes small, maintainable, and generic. Do not hardcode smoke-case answers into runner logic.
- The runner owns task order, retry state, review state, and `.ai-task-runner/state.json`.
- Agents being executed by the runner write task deliverables; runner code only orchestrates, monitors, retries, reviews, and validates.
- Use `ai_task_runner.py` or `runner.api` as the public entry points.
- For tests, run focused pytest targets first, then `python -m pytest` before finalizing broad changes.
- Read `docs/PROJECT_GUIDE.md` for project structure and the 24h execution model.
