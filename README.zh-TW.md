# AI Task Runner

版本：1.2.2

這是一個小型、可重用、適合長時間執行 AI coding task 的 Python orchestrator。它把模型工作與 deterministic validation 分離，保留可 Resume 的狀態，限制 Executor 只處理目前 TODO，並在模型或 CLI 不穩定時持續恢復，而不把專案需求 hardcode 進 Runner。

## 核心能力
- 支援 Qwen / OpenCode；Qwen Prompt 僅走 stdin，不使用 `-p` 傳完整 Prompt。
- Adaptive Planning：bounded read-only Understand -> 同一 planning client/session 的 Plan Finalize -> 必要時同 session Judge/Rewrite；只有 planning session 無法恢復時才用 fresh full-context fallback。
- TODO 隔離執行：Executor 跨 TODO 沿用同一 session，每次只送新的 Current TODO 與 scope 提醒；Review 才使用 fresh read-only session。
- Deterministic Final Validator 是 hard gate；可單獨使用 Final AI Validator，也可在 hard gate PASS 後追加 fresh-session AI 投票。
- Retry / Resume、session rebuild、no-progress recovery、protected paths、Git write guard、JSONL events、Python API、YAML script mode（每筆可指定 `project_root`，goal 可用 `goal_file`）。
- 所有模型 structured result 共用同一套 parser：外層寬鬆、payload/schema 嚴格。
- bounded debug history，保留 current/last prompt/result 與最近歷史。
- `<project-root>/.ai-task-runner.yaml` 是專案 policy；policy 本身會自動受到保護。

## 快速開始
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py"
```

Validator 額外參數可重複指定：
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --validator-arg "--fab" --validator-arg "FAB23"
```
Runner 實際呼叫會是 `python validation.py --project-root <root> --state-file <state> --fab FAB23`。不要把 `--fab FAB23` 塞進 `--validator` 的檔案路徑字串。

Hard + AI 混合驗證：
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --ai-validator-prompt "檢查架構與通用性" --ai-validator-count 3
```
Python validator 必須先 PASS；之後 3 個 fresh AI session 獨立投票，預設採嚴格過半。

## 文件地圖
- [完整文件索引](docs/INDEX.zh-TW.md) / [English index](docs/INDEX.md)
- [English README](README.md)
- [完整設計](docs/DESIGN.zh-TW.md) / [Design](docs/DESIGN.md)
- [架構](docs/ARCHITECTURE.zh-TW.md) / [Architecture](docs/ARCHITECTURE.md)
- [使用指南](docs/USER_GUIDE.zh-TW.md) / [User Guide](docs/USER_GUIDE.md)
- [CLI 參考](docs/CLI_REFERENCE.zh-TW.md) / [CLI Reference](docs/CLI_REFERENCE.md)
- [Python API](docs/API_REFERENCE.zh-TW.md) / [API Reference](docs/API_REFERENCE.md)
- [Prompt / Session](docs/PROMPT_SESSION.zh-TW.md) / [Prompt / Session Contract](docs/PROMPT_SESSION.md)
- [State / Events](docs/STATE_EVENTS.zh-TW.md) / [State / Events](docs/STATE_EVENTS.md)
- [保護與安全](docs/SECURITY_PROTECTION.zh-TW.md) / [Protection / Safety](docs/SECURITY_PROTECTION.md)
- [24H 運行與故障排查](docs/OPERATIONS.zh-TW.md) / [Operations](docs/OPERATIONS.md)
- [專案 / 維護者指南](docs/PROJECT_GUIDE.zh-TW.md) / [Project Guide](docs/PROJECT_GUIDE.md)
- [測試矩陣](docs/TEST_MATRIX.zh-TW.md) / [Test Matrix](docs/TEST_MATRIX.md)
- [Validator 範本](docs/validator_templates/README.zh-TW.md)
- [Examples](examples/README.zh-TW.md)
- [Smoke](smoke/README.zh-TW.md)

## 維護契約
請遵守 `AGENTS.md` 與 `QWEN.md`：禁止 project-specific hardcode；同類行為只保留一個共用 implementation/function；以最小程式碼解決已證明的問題；程式碼必須精簡、清楚、容易維護。
