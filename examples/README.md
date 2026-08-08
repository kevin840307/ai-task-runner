# Examples

Version: 1.1.1

Examples demonstrate end-to-end Runner patterns: file generation, structured documents, CLI tools, AI validation, YAML multi-step scripts, and config rendering. Each example project root has its own `.ai-task-runner.yaml`; immutable inputs/reference fixtures are protected while required outputs remain writable. Validators use `validator_interface.py`.

Run the provided `run_qwen.ps1` / `run_opencode.ps1` where available, or invoke `ai_task_runner.py` directly with the example prompt/project/validator. For validator-specific CLI inputs, use repeatable `--validator-arg`.
