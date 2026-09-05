# AI Task Runner

版本：1.2.61

Example 啟動器預設使用隔離副本：`examples\run_examples.bat` 與每個 `examples\*/run_example.bat` 都只會把選定的 Example（`--all` 時才複製 examples 集合）複製到新的 `<repo>\.example_runs\...` 工作區，再由原專案 Runner 執行，因此 canonical fixture 每次測試後都維持原狀。


執行完成規則：內層正常 return 不代表任務完成；只有持久化 state 同時確認 `completed=true` 且 `stage=completed`（Final Validator PASS 狀態）才算完成。正式 `runner.api.run()` 會自動 resume 未完成 state；CLI 只額外提供 worker-process crash isolation。Task Recovery 依重複相同的無進展證據升級（same session -> fresh session -> replan），不依總 attempt 次數放棄。

這是一個小型、可重用、適合長時間執行 AI coding task 的 Python orchestrator。它把模型工作與 deterministic validation 分離，保留可 Resume 的狀態，限制 Executor 只處理目前 TODO，並在模型或 CLI 不穩定時持續恢復，而不把專案需求 hardcode 進 Runner。

## 核心能力
- Bounded structured Stage handoff：Recover Prompt 可直接使用 `previous.data`（例如 `reason`／`missing_items`），不需重送無上限的既有 Context。
- 支援 Qwen / OpenCode；兩者完整 AI task Prompt 都只走 stdin，session / permission 差異由 Backend adapter 負責。
- Declarative Planning：Plan 直接產生 durable TODO list；Planning failure 走共用 same-session -> fresh-session -> replan recovery，沒有獨立 Understand/Judge Stage。
- TODO 隔離執行：每個 TODO 依序 Execute -> Review；同 TODO failure 優先 Same Session，必要時才 Fresh Session。Timeout recovery 使用穩定語意 failure key，因此 sandbox/container ID 等動態 backend output 不會把同一 failure 誤判成新 failure。Review 使用獨立 read-only client/session。
- Builtin Execute/Review 在同一 Session 已看過完整 Stage contract 後，使用 bounded `continuation_prompt` 只補新的 TODO／Repair／Review evidence，不重送 Goal/rules；第一次與 Fresh/Rebuilt Session 仍取得完整必要 Context。
- Deterministic Final Validator 是 hard gate；可單獨使用 Final AI Validator，也可在 hard gate PASS 後追加 fresh-session AI 投票。
- Retry / Resume、session rebuild、no-progress recovery、protected paths、Git write guard、JSONL events、CLI/Python/UI 共用的 canonical API boundary、線性 Workflow YAML、YAML script mode（每筆可指定 `project_root`、`goal_file`、`workflow_file`）。
- Worker crash/中斷 cleanup 會依每個 durable Run 的實際 work directory 處理，包含 YAML List child，避免遺留 AI/sandbox orphan process；所有 subprocess stdout 路徑都會 bounded，`KeyboardInterrupt` / `SystemExit` 不會進入 Stage retry/recovery。
- Resume 以合法的 project `state.json` 為 authoritative state，只有 primary state 缺失或損壞時才使用 temp backup，避免 crash window 後被 stale backup 回滾。
- UI-ready extension boundary：UI/editor 直接使用各能力的 owner module（`runner.resources`、`runner.workflow.loader` / `registry`、`runner.prompts.loader`）；Workflow validation 前可註冊 installed Stage/Backend、runtime Plugin 可外掛，Workflow/Prompt 支援 atomic edit，且每個 Run 都有自己的 Workflow／Stage Prompt／Goal／Final-AI Prompt snapshot。
- 本機 detached UI 可以完全不 import Runner：直接讀 project work directory 的 runtime visibility files（`state.json` 看目前 durable 狀態、`runner-process.json` 看 active Supervisor/Worker PID identity、`stream.log` 看最近 bounded subprocess output、`log.txt` / `debug/` 做診斷）。`stream.log` 與 `runner-process.json` 只提供 visibility/control metadata，絕不可改變 Workflow 語意。本機 detached UI 若要停止 Runtime，只需建立 `.ai-task-runner/stop.request`；Supervisor 會 consume request、終止目前 Worker/其 owned child process，並以 130 結束。Resume / Rerun 不使用 request file，而是重新啟動 CLI 並使用 `--resume` / `--force-new`。
- 通用 `command` Stage 統一負責所有 subprocess execution，包括 project/user Python 與 deterministic File Validator。
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
file validator 必須先 PASS；之後 3 個 fresh AI session 獨立投票，預設採嚴格過半；`--ai-validator-required-passes` 可明確要求例如 3/3。

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

Runner 使用精簡的 YAML-driven Flow Pipeline。`StageExecutor` 統一處理 retry、Hook、semantic progress 與 exception；每個 Stage 只做自己的工作並回傳 `StageResult` facts/effects。`recover`、`restart_at`、`scope` 這類 routing 屬於 `FlowNode`。`PlanStage` 是內建 Task Producer，並會自動進入標準 `execute -> review` 的逐 TODO SOP，因此一般 Plan-driven YAML 不需要重複寫這兩個 flow node。其他 Stage 仍可用 `produces: tasks` 產生 Task；只有進階／自訂 Producer 或自訂逐 Task SOP 才需要顯式 `scope: task` block。

橫切功能不進 Flow：Status Event 提供 UI / Logging / Diagnostics 訂閱；Git 限制、檔案保護、ReadOnly 與可選的 Loop context 壓縮都透過 Plugin 註冊。Core Stage 與 AI Client 不 import 這些具體 Plugin；Workflow 也不依賴 raw event schema。


## Stage 執行架構

`YAML FlowNode -> StageExecutor -> Stage.run() -> StageResult -> recovery / next FlowNode`

統一執行規則：
- API／服務異常由 AI client 做指數退避，每個等待視窗預設最多 1 小時；不計入 Stage failure。視窗用盡後，正式 `runner.api.run()` 會從 direct/YAML durable state 自動 resume 並開啟下一個視窗，直到任務 PASS。
- 真實 failure 先使用 same-session 的短 Stage-aware 續跑 prompt，只補 Stage 身分、新 failure evidence 與下一步；達到 retry 次數（預設 2）後由 StageExecutor 建立 fresh session。
- fresh session 仍持續同一 failure 時回傳 `replan`，預設 flow 會啟動 Fresh Planning Session 並重新產生 plan；Stage 也可用共用的 1-based YAML `restart_at` 改從目前或更前面的指定頂層 Stage 開始；failure 不同則重新計數。
- write attempt 只要有實際 project change 就視為有 progress，不累積 failure，直接交給下一個 review／validation Stage 判斷。
- Review retry 用盡後可 skip；skip 會留下 evidence，Final Validator 仍是唯一完成 gate。
- Task Producer 只保存 durable TODO 內容（`title`、`description`、`deliverable`、`acceptance_criteria`）。`PlanStage` 是內建 Producer；`command` 或未來 Stage 也可用 `produces: tasks` 產生相同效果。Plan-driven flow 由 Loader 內部展開標準 `execute -> review` task SOP，`workflow_position` 仍是 durable cursor；顯式 `scope: task` 保留給進階／自訂 Task Producer 或自訂逐 Task SOP。


Stage 一次只做一個 attempt。Hook/semantic progress/change tracking 由 `StageExecutor` 統一處理；Retry 與下一步路由只屬於 Flow。一般行為共用 `BaseStage`，Plan 等 AI 特殊語意使用專用 Stage；所有 subprocess 工作統一使用 `CommandStage`。


## 新增普通 AI Stage

一般 AI 工作只使用 YAML 的 `stages` 與 `flow`：`stages` 定義可重用 node，`flow` 組裝流程，且每次 invocation 都能覆寫 `prompt`、`retry`、`skip` 等欄位。一般 AI-backed node 使用 `BaseStage`，`type` 預設為 `base`，通常可省略；只有 `plan`、`task`、`review`、`ai_validator`、`command` 或真正的自訂 Stage 才需要明寫 `type`。

```yaml
stages:
  security_check:
    status: Security review
    prompt: stages/workflow_prompt.md
    instructions_file: prompts/security_check.md

flow:
  - security_check
```

真正的新行為只新增一個帶 `spec_class` 的 Stage class，再做一次 `register_stage("type", StageClass)`。Registry 只保留 `type -> class`；retry、prompt、recovery、validator capability 與流程組合都放 YAML。Planning 專用動態 context 仍由 `PlanStage` 負責。Prompt 變數統一由 `runner/prompts/context.py` 管理；Template 使用 Jinja `StrictUndefined`。


## OpenCode Backend

OpenCode 與 Qwen 共用同一 Runner Stage/Session/Recovery contract：完整 Prompt 走 stdin、既有 Session 使用 `--session`、JSON event 解析 `text/error/step_finish`，且 non-interactive call 會使用 `--auto`。`--sandbox` 在 OpenCode 上映射為 runtime `permission`：禁止 `external_directory`；Planning/No-tool/Review 另外依 Stage mode 套用 read-only/no-tool 權限。這不是 Qwen 的 container sandbox；真正 protected path/Git/readonly 保護仍由 Runner Plugin 執行。


### Flow Label

`status` 屬於可重用的 Stage 定義；FlowNode 可選的 `label` 只描述這一次具體工作，不改變 Stage 行為：

```yaml
stages:
  run_prompt:
    type: task
    status: AI running skill

flow:
  - stage: run_prompt
    label: Project Documentation
    prompt: skills/project_documentation.md
```

Runner event 仍保留 `status=AI running skill`，並提供 `label=Project Documentation`；Console/UI detail 顯示 label。未設定 `label` 時完全維持既有行為。


### 重複 Semantic FAIL 的 Fresh Session Escape

FlowNode 可用 `fresh_after_same_failures: N` 覆寫預設值。只有成功解析出的 semantic `FAIL` 才計數；同一 failure fingerprint 連續達 N 次時，只清掉該 Stage 自己的 AI session，照原本 `recover` 修復後，再以 Fresh Session + 完整 Prompt 重跑該 Stage。Backend/API/parser/timeout 等技術異常不計數，不同 semantic failure 會重置計數。`ReviewStage` 在有 recovery 時直接擁有語意預設 `2`；其他 Stage 仍是 opt-in。這樣 builtin YAML 不必重複 implementation policy，但需要特殊門檻時仍可由 Workflow 明確 override。

## Workflow Dry Run

可使用 `tool/workflow_dryrun.py` 在不呼叫真實 Agent 的情況下驗證 `workflow.yaml` 是否能閉環。工具直接重用正式 Workflow Loader、Pipeline、StageResult 與 Stage finish 與 result reducer，只 Mock 最底層 Stage 執行結果，因此不會建立第二套 Workflow Engine。

```bat
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --scenario dryrunexample\builtin_mixed_scenario.yaml
dryrunexample\run_dryrun.bat
```

`dryrunexample/` 同時示範 builtin workflow，以及使用 `task`、`review`、recover、`repeat` 的精簡自訂 workflow 閉環測試。Dry Run 是外部工具；刪除整個工具與範例不會改變 Runner Core 行為。
自動 Failure Matrix：

```bat
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --matrix
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --matrix --json

`--matrix` 現在會依 Workflow 實際存在的 `recover`、`repeat`、`restart_at` 產生 deterministic routing cases，並回報偵測到的 task producer/task scope/review/validation 等 feature；`--matrix --json` 可直接供 CI、UI 與 reliability gate 使用。
```

`--matrix` 會測 Happy Path，並針對正式 normalized workflow 中每個具有 recover 的 Stage，自動注入一次 `FAIL -> recover -> closure`。非法 Workflow 參數會先由正式 Workflow Loader/schema 擋下；Dry Run 不維護第二套重複的 validation 規則。



### Command-backed Stages
`command` 是唯一的 child-process Stage，統一執行 Python script、File Validator 與任意 argv，並共用 cwd、timeout、output capture、process-tree cleanup 與 exit-code semantics。

## 本機 UI

提供獨立入口的輕量 GPT-style 本機 UI：

```bash
python ui/main.py
```

UI 不 import Runner Core；它只啟動既有 CLI，並讀取 Project `.ai-task-runner` runtime files。一個 Project 對應一條持久對話。
