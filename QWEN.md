# Qwen Development Rules

Follow `AGENTS.md`; the same rules are mandatory for Qwen-driven maintenance.

- No hardcoded project-specific behavior in generic Runner code.
- Reuse one shared function for the same behavior; do not duplicate implementations.
- Use the minimum code necessary and keep it easy to read.
- Preserve unrelated behavior and existing public interfaces unless the task requires a change.
- Current TODO is the only executable scope. Never implement later TODOs merely because the Original Goal is visible.
- Same-session continuation prompts should contain only new stage-aware feedback/instructions. Fresh/rebuilt sessions must be self-sufficient.
- Final AI validation runs use independent fresh sessions; N configured validations means N different sessions. Structured-output repair is bounded to two same-session retries before fresh fallback.
- Use the shared structured-result parser; do not create stage-specific JSON extraction logic.
- Qwen prompt transport is stdin-only. Do not place the full prompt in `-p` or argv; this avoids Windows command-line limits and keeps one input route.
- Never modify protected paths or the project-root `.ai-task-runner.yaml`.
- Never run `git add`, `git commit`, or `git push`.
- Do not change validators or immutable fixtures to make a failing implementation pass.
