# Examples 範例

版本：1.1.1

Examples 展示完整 Runner 使用方式：檔案生成、structured Markdown、CLI 工具、AI Validation、YAML multi-step script、config renderer。每個 example project root 都有自己的 `.ai-task-runner.yaml`；immutable input/reference fixture 會 protected，而需求要產生/修改的 target 保持 writable。Validator 統一使用 `validator_interface.py`。

可使用案例內 `run_qwen.ps1` / `run_opencode.ps1`，或直接用 `ai_task_runner.py` 搭配 prompt/project/validator。Validator 若需要額外 CLI input，使用可重複的 `--validator-arg`。
