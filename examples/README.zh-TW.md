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

YAML 每筆 task 都有自己的 `project_root`；相對路徑以外層 `--project-root` 為基準。Validator 與 prompt 放在各 writable project root 外面；`examples.yaml` 使用 `goal_file` 引用每個 `prompt.md`。
