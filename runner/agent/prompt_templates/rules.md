Hard rules:
- You may READ files anywhere when necessary.
- You may WRITE/CREATE/DELETE files only inside project root: $root
- Treat every path outside project root as read-only. Do not create sidecar state, log, report, or scratch files next to outside-root paths.
- Never modify these protected paths:
$protected_names
- Never modify runner state directly. Python owns task state.
- Never run `git add`, `git commit`, or `git push`; Git acceptance and publication are human-review actions. Read-only Git commands are allowed.
- Preserve unrelated behavior and public interfaces unless the current goal explicitly requires changing them.
- Do not invent files, credentials, APIs, test results, or facts. Report unavailable evidence honestly.
