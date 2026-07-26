# Examples

All commands below are intended to run from the repository root. Each example is a small starter project that the AI modifies in place. Use `run_qwen.ps1` or `run_opencode.ps1`. Delete the example project's `.ai-task-runner` directory before repeating a finished run, or use a fresh copy.

| Example | Input mode | Validator | Purpose |
|---|---|---|---|
| `01_config_template_roundtrip` | Single prompt | Python | Compress four repeated configs into one template plus a line-limited values file, render them, and compare byte-for-byte. |
| `02_structured_markdown_report` | Single prompt | Python | Generate Markdown with fixed headings, tables, ordering, and content. |
| `03_csv_summary_cli` | Single prompt | Python | Build a deterministic standard-library CSV summary CLI with invalid-input handling. |
| `04_ai_validator_bugfix` | Single prompt | Fresh AI session | Fix a small library, add tests, and let an independent AI validator inspect behavior and documentation. |
| `05_yaml_release_pipeline` | YAML array | Python + AI | Execute version support, changelog generation, and README verification as sequential work items. |
| `06_yaml_data_migration_pipeline` | YAML array | Python + AI | Build a CSV-to-JSON migration utility, required-format documentation, and an independent final review. |

## Single-prompt example

```powershell
./examples/01_config_template_roundtrip/run_qwen.ps1
```

The script reads `prompt.txt`, then passes it as `--goal`. The validator is protected from model modification and is run only after all generated tasks are complete.

## YAML example

```powershell
./examples/05_yaml_release_pipeline/run_qwen.ps1
```

Each YAML array item contains its own `prompt`, `validator`, and optional `validator_prompt`. Items run in order. Each item has an independent main session; `validator: ai` creates a separate fresh validation session. Add `--resume` to the launcher command to skip completed items and continue the interrupted item from its saved session.

## Notes

- File validators receive `--project-root` and `--state-file`. Exit code 0 means PASS.
- Example validators intentionally inspect generated behavior, not only file existence.
- Examples 01–03 use deterministic Python validators; example 04 demonstrates AI-only validation; examples 05–06 demonstrate mixed YAML pipelines.
