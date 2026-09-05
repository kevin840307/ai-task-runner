# Local UI

A small GPT-style local UI for AI Task Runner.

```bash
python ui/main.py
```

Design rules:

- UI has its own `main()` and does not import `runner.*`.
- One project maps to one persistent conversation.
- UI reads `.ai-task-runner/state.json`, `runner-process.json`, and `stream.log`.
- Stop writes `.ai-task-runner/stop.request`.
- Resume/Rerun launch the existing CLI with `--resume` / `--force-new`.
- Conversation history is UI-owned at `.ai-task-runner/ui/messages.jsonl`.
- No reasoning/thinking view is exposed; only current live subprocess output is shown.
