{{ rules }}

Goal:
{{ goal }}

This is an intentional live concurrency / Git merge-recovery test.

Execution rules:
- Work only inside the current project/worktree.
- Modify only shared.txt unless the Goal explicitly says otherwise.
- Do not run git, git checkout, git reset, git merge, git rebase, or git clean.
- Do not edit .ai-task-runner, workflow YAML, prompt files, QWEN.md, or test harness files.
- Preserve all existing enabled_tasks entries that are not being removed by the Goal.
- Keep shared.txt as exactly one UTF-8 text line in this format:
  enabled_tasks=NAME1,NAME2,...
- Do not duplicate entries.
- Read shared.txt before editing it.
- After editing, read shared.txt again and verify the requested entry exists while prior entries are preserved.
- Return a concise factual summary only after the file is correct.
