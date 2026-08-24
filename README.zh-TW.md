# AI Task Runner

版本：1.2.33


執行完成規則：內層正常 return 不代表任務完成；只有持久化 state 同時確認 `completed=true` 且 `stage=completed`（Final Validator PASS 狀態），CLI 才會退出。若 state 尚未完成，main 會自動 resume 繼續。Task Recovery 依重複相同的無進展證據升級（same session -> fresh session -> replan），不依總 attempt 次數放棄。

這是一個小型、可重用、適合長時間執行 AI coding task 的 Python orchestrator。它把模型工作與 deterministic validation 分離，保留可 Resume 的狀態，限制 Executor 只處理目前 TODO，並在模型或 CLI 不穩定時持續恢復，而不把專案需求 hardcode 進 Runner。

## 核心能力
- 支援 Qwen / OpenCode；Qwen Prompt 僅走 stdin，不使用 `-p` 傳完整 Prompt。
- Declarative Planning：Plan 直接產生 durable TODO list；Planning failure 走共用 same-session -> fresh-session -> replan recovery，沒有獨立 Understand/Judge Stage。
- TODO 隔離執行：每個 TODO 依序 Execute -> Review；同 TODO failure 優先 Same Session，必要時才 Fresh Session。Review 使用獨立 read-only client/session。
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
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --ai-validator-prompt-file "ai_validation.md" --ai-validator-count 3
```
Python validator 必須先 PASS；之後 3 個 fresh AI session 獨立投票，預設採嚴格過半；`--ai-validator-required-passes` 可明確要求例如 3/3。

## 文件地圖
- [完整文件索引](docs/INDEX.zh-TW.md) / [English index](docs/INDEX.md)
- [English README](README.md)
- [完整設計](docs/design/DESIGN.zh-TW.md) / [Design](docs/design/DESIGN.md)
- [架構](docs/design/ARCHITECTURE.zh-TW.md) / [Architecture](docs/design/ARCHITECTURE.md)
- [使用指南](docs/user/USER_GUIDE.zh-TW.md) / [User Guide](docs/user/USER_GUIDE.md)
- [CLI 參考](docs/user/CLI_REFERENCE.zh-TW.md) / [CLI Reference](docs/user/CLI_REFERENCE.md)
- [Python API](docs/user/API_REFERENCE.zh-TW.md) / [API Reference](docs/user/API_REFERENCE.md)
- [Prompt / Session](docs/design/PROMPT_SESSION.zh-TW.md) / [Prompt / Session Contract](docs/design/PROMPT_SESSION.md)
- [State / Events](docs/design/STATE_EVENTS.zh-TW.md) / [State / Events](docs/design/STATE_EVENTS.md)
- [保護與安全](docs/operations/SECURITY_PROTECTION.zh-TW.md) / [Protection / Safety](docs/operations/SECURITY_PROTECTION.md)
- [24H 運行與故障排查](docs/operations/OPERATIONS.zh-TW.md) / [Operations](docs/operations/OPERATIONS.md)
- [專案 / 維護者指南](docs/development/PROJECT_GUIDE.zh-TW.md) / [Project Guide](docs/development/PROJECT_GUIDE.md)
- [測試矩陣](docs/development/TEST_MATRIX.zh-TW.md) / [Test Matrix](docs/development/TEST_MATRIX.md)
- [Validator 範本](docs/validator_templates/README.zh-TW.md)
- [Examples](examples/README.zh-TW.md)
- [Smoke](smoke/README.zh-TW.md)

## 維護契約
請遵守 `AGENTS.md` 與 `QWEN.md`：禁止 project-specific hardcode；同類行為只保留一個共用 implementation/function；以最小程式碼解決已證明的問題；程式碼必須精簡、清楚、容易維護。

### 可選的 Loop context 壓縮
預設關閉。只有明確開啟 `--loop-context-compress` 後，Loop Detection 且目前 context 使用率達 `--loop-context-compress-threshold 50` 才會嘗試壓縮。拿不到實際 context 使用率就跳過；一般 retry、API timeout/429/5xx 不會觸發。Qwen backend 使用 session `/compress-fast`。

YAML task 也可設定 `loop_context_compress: true` 與 `loop_context_compress_threshold: 50`。

## Flow Engine 架構

Runner 現在使用精簡的 Stage List Pipeline。`StageExecutor` 統一處理 retry、Hook、semantic progress 與 exception；每個 Stage 只做自己的工作並回傳 `StageResult`。Result 可動態帶 `next_flow`、用 `replace_remaining` 取代剩餘 flow、停止或完成；Pipeline 只消費這些資訊，不 hardcode review/repair/validation 路線。

橫切功能不進 Flow：Status Event 提供 UI / Logging / Diagnostics 訂閱；Git 限制、檔案保護、ReadOnly 透過透明 Execution Hook 註冊。Core 與 Stage 不 import 這些具體 Plugin；Workflow 也不依賴 raw event schema。


## Stage 執行架構

`Pipeline loop -> StageExecutor -> Stage.run() -> StageResult -> next_flow/replace_remaining/complete -> next Stage`

統一執行規則：
- API／服務異常由 AI client 做指數退避，每個等待視窗預設最多 1 小時；不計入 Stage failure。
- 真實 failure 先使用 same-session 的短 Stage-aware 續跑 prompt，只補 Stage 身分、新 failure evidence 與下一步；達到 retry 次數（預設 2）後由 StageExecutor 建立 fresh session。
- fresh session 仍持續同一 failure 時回傳 `replan`，預設 flow 會啟動 Fresh Planning Session 並重新產生 plan；failure 不同則重新計數。
- write attempt 只要有實際 project change 就視為有 progress，不累積 failure，直接交給下一個 review／validation Stage 判斷。
- Review retry 用盡後可 skip；skip 會留下 evidence，Final Validator 仍是唯一完成 gate。
- Plan 把 TODO list 存入 durable state，並直接回傳由 `[execute, review]` 組成的 execution list。Pipeline 先完整執行這個巢狀 list，再回到外層繼續 Python/AI Validator；未來任何 Stage 都可以用相同方式回傳 Stage list。


Stage 一次只做一個 attempt。Hook/semantic progress/change tracking 由 `StageExecutor` 統一處理；Retry 與下一步路由只屬於 Flow。一般行為共用 `AIStage`，Plan 或 Python Validator 這種特殊行為才使用 `PlanStage` / `PythonValidatorStage`。


## 新增普通 AI Stage

普通 AI Stage 直接資料化，不需要新增 Python prompt builder：

```python
"security_review": {
    "stage": "ai",
    "status": "AI 正在執行 Security Review",
    "mode": "readonly",
    "prompt": "stages/security_review.md",
}
```

再把 `"security_review"` 插入 `FLOWS` 的目標位置，並新增 `runner/prompts/stages/security_review.md`。Stage preset 的 key 會自動成為 Stage name。Planning 專用的動態 context 由 `PlanStage` 負責，不再有獨立 prompt-builder registry。Prompt 變數統一由 `runner/prompts/context.py` 管理；Template 使用 Jinja `StrictUndefined`，禁止直接讀 runtime 內部物件。
