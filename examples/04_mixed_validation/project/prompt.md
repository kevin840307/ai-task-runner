Build todo_cli.py, a persistent JSON Todo CLI.

Global option:
  --db <path>
Commands:
  add <text> --priority low|medium|high
  list --format json
  done <id>
  delete <id>

Requirements:
- Store a JSON array in the selected --db file.
- IDs are stable increasing positive integers; deleting an item must not reuse its ID while higher IDs remain.
- New items have done=false.
- done marks only the requested item.
- delete removes only the requested item.
- list --format json prints the full array as valid JSON.
- Missing DB starts as an empty list.
- Unknown IDs and invalid priority return non-zero.
- Keep the code generic, small, and free of validator-specific or sample-data hardcoding.
