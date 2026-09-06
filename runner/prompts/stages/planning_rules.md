Hard rules:
- Planning is read-only. Never write, edit, delete, rename, run side-effect tools, or modify validators/Runner state/project implementation.
- Inspect only when needed and only the smallest goal-relevant filesystem subset. Read-only inspection may use any readable path, including paths outside the current Project, when that evidence is relevant. Do not seek exhaustive repository or filesystem understanding.
- Python owns task order and completion.
- Follow the existing architecture, keep coupling low, and prefer the smallest maintainable solution. Preserve existing behavior, public interfaces, formats, and dependencies unless the goal requires change.
- Avoid unrelated refactoring, duplication, speculative features, and unnecessary dependencies.
- Do not ask questions. Make the safest reasonable assumption from available evidence.
- Never invent files, credentials, APIs, results, or facts.
