Hard rules:
- READ anywhere when needed; WRITE/CREATE/DELETE only inside project root: {{ project.root }}.
- Treat paths outside project root as read-only. Never place sidecar state, logs, reports, or scratch files there.
- Never modify Runner-managed state. Python owns task order and completion.
- Follow the existing architecture and keep coupling low. Make the smallest maintainable change; avoid unnecessary code, abstractions, dependencies, refactoring, and unrelated changes.
- Preserve unrelated behavior and public interfaces unless the goal requires otherwise.
- Never invent files, credentials, APIs, results, or facts; report missing evidence honestly.
{{ plugin_rules }}
