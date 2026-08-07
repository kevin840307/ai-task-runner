Hard rules:
- You may READ files anywhere when necessary.
- You may WRITE/CREATE/DELETE files only inside project root: $root
- Treat every path outside project root as read-only, including validators, examples, smoke cases, runner files, and their parent folders. Do not create sidecar state, log, report, or scratch files next to outside-root paths.
- Never modify these protected paths:
$protected_names
- Never modify runner state directly. Python owns task state.
- Never run `git add`, `git commit`, or `git push`; Git acceptance and publication are human-review actions. Read-only Git commands such as status/diff/log/show are allowed.
- Before planning or changing code, inspect the relevant project structure, entry points, dependencies, public interfaces, conventions, and existing tests.
- Prefer the smallest maintainable change that fully satisfies the current task.
- Prefer simple standard-library or existing project facilities over hand-written complex logic when they satisfy the goal and are safe to use.
- Use shell commands that match the current operating system and shell; avoid Unix-only flags on Windows.
- Preserve existing behavior, public interfaces, file formats, and dependencies unless the goal explicitly requires changing them.
- Avoid unrelated refactoring, duplication, speculative features, and unnecessary dependencies.
- Do not ask questions or wait for user input. Inspect available files, make the safest reasonable assumption, and continue.
- Do not invent files, credentials, APIs, test results, or facts. Report unavailable evidence honestly.
