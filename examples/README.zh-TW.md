# 範例

Windows 一次依序執行全部範例：

```bat
examples\run_examples.bat
```

可把一般 Runner 參數直接接在 BAT 後，例如 `examples\run_examples.bat --backend qwen --resume`。

這套範例刻意保持小而容易定位問題：

1. `01_basic_python_validator`：Python 硬性驗證 baseline。
2. `02_repair_cycle`：內建 starter bug，驗證 Validator FAIL → Repair。
3. `03_ai_validator_voting`：AI-only Final Validator，3 個獨立 fresh session 投票。
4. `04_mixed_validation`：Python hard gate + AI semantic majority vote。
5. `05_ai_quality_repair`：硬性功能驗證 + AI 通用性/品質 gate。
6. `06_yaml_driven_tool`：小型 YAML 應用；外層 `examples.yaml` 同時驗證 Runner YAML batch mode。
7. `07_blackbox_medium`：中型黑盒案例，Validator 只驗 CLI output，完全不檢查實作結構。
8. `08_config_driven_data_pipeline`：混合驗證的資料管線案例，以黑盒行為檢查為主。
9. `09_config_environment_auditor`：混合驗證的設定檔稽核案例，涵蓋多種格式與乾淨重跑。
10. `10_skill_prompt_review_workflow`：可實跑的 custom workflow 範例，重用單一 prompt Stage 執行 `/skill...` prompt、review gate，最後由 Python validator 驗證。

所有 Python example Validator 都統一使用共用的 `ai_task_runner_validator.ValidatorReport` 契約。功能失敗透過 `ValidatorReport.error()` 回報；適用的 JSON output 使用 `parse_json()`；完整報告會寫入各 project 的 `.ai-task-runner/validator-reports/`。


每個 YAML item 都有自己的 `project_root`；相對路徑以外層 `--project-root` 為基準。每個 project 會把 `prompt.md`、Python `validation.py` 與可選的 `ai_validation.md` 放在自己的 root 內，並由 `.ai-task-runner.yaml` 的 `protected_paths` 明確保護；policy 本身也會自動受保護。`examples.yaml` 使用 `goal_file` 與 `ai_validator_prompt_file` 引用這些檔案。

Workflow Schema 範例放在 `workflows/`。`workflows/skill_prompt_review_chain.yaml` 展示一個可重用 prompt Stage，搭配由使用者在開頭自行寫入 `/skill...` 指令的 prompt，以及可重用的 Review invocation；`workflow_multi_prompt.yaml` 則保留為原本精簡的 multi-prompt 範例。`10_skill_prompt_review_workflow` 會用真實 project 和 validator 實跑這個 workflow。

驗證模式 Workflow 範例：`validation_modes.yaml` 展示自動內建對應：

- 只有 Python file validator 時選用 `runner/workflow/builtin/file.yaml`。
- `validator: ai` 時選用 `runner/workflow/builtin/ai.yaml`。
- Python file validator 加上 `ai_validator_prompt` 或 `ai_validator_prompt_file` 時選用 `runner/workflow/builtin/mixed.yaml`。
