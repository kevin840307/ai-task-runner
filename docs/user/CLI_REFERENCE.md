# CLI Reference

Version: 1.2.15

All CLI options map to the canonical `RunRequest`. Repeatable options append one argv element each.

| Option | Meaning | Default / notes |
|---|---|---|
| `--goal` | Inline goal | mutually exclusive with `--goal-file` |
| `--goal-file` | UTF-8 goal file | preferred for long goals |
| `--project-root` | writable project boundary | `.` |
| `--script` | YAML task array; items may use `prompt`/`goal` or `goal_file` | exclusive with goal |
| `--validator` | Python validator path or `ai` | required outside script mode |
| `--validator-prompt` | extra Final AI instructions for `--validator ai` | empty |
| `--ai-validator-prompt` | optional Final AI instructions after a file validator passes | empty/off |
| `--ai-validator-prompt-file` | UTF-8 file containing Final AI validation instructions; mutually exclusive with `--ai-validator-prompt` | empty/off |
| `--backend` | `qwen` or `opencode` | `qwen` |
| `--command` | backend executable override | backend default |
| `--sandbox` | run agent calls in the backend sandbox | off; Qwen adds `-s` |
| `--agent-arg` | one extra backend argv element | repeatable |
| `--validator-arg` | one extra validator argv element | repeatable |
| `--protect-file` | additional protected file/directory | repeatable |
| `--validator-timeout` | validator seconds | 1200; positive |
| `--agent-timeout` | runtime AI-call seconds | 7200; 0 disables |
| `--planning-timeout` | planning AI-call seconds | 600; 0 disables |
| `--agent-idle-after-change-timeout` | idle seconds after changes/output stop | 900; 0 disables |
| `--max-attempts` | per-task attempt cap | 0 = unbounded by count |
| `--max-cycles` | repair-cycle cap | 0 = unbounded by count |
| `--retry-delay` | logical task retry delay | 2 seconds |
| `--retry-wait` | initial model-call retry wait | 5 seconds |
| `--retry-max-wait` | max model-call retry wait | 300 seconds |
| `--final-ai-validations`, `--ai-validator-count` | independent fresh-session Final AI votes | 1 |
| `--final-ai-required-passes` | required PASS count | 0 = strict majority; otherwise <= runs |
| `--work-dir` | Runner state dir inside project root | `.ai-task-runner` |
| `--json-events` | emit JSON Lines progress | off |
| `--resume` | resume state | off |
| `--force-new` | create new run | off; conflicts with resume |
| `--plan-only` | plan/save/exit before execution | off |

## Validator command construction
For `--validator validation.py --validator-arg --fab --validator-arg FAB23`, Runner executes conceptually:
`<python> validation.py --project-root <root> --state-file <state.json> --fab FAB23`.
Arguments are not parsed as business semantics by Runner.
