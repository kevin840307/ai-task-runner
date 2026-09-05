# 專案與 AI / 維護者開發指南

版本：1.2.53

## 強制維護規則
1. 最少 Code；Generic Runner 禁止 project-specific hardcode。不可為單一 sample/project 寫專案名稱、FAB/ENV/version、filename、business field 或特定 AI identity 分支。
2. 不影響目前 24H 穩定執行，包括 YAML List、多次 programmatic `run()`、Resume 與 Supervisor recovery。
3. Log/Event 要精簡但足以 Debug；不要大量輸出重複 Context。
4. Workflow 不依賴具體 Plugin、Qwen/OpenCode implementation 或 raw event schema；Cross-cutting behavior 必須透過 Plugin/Hook/runtime semantic facade 接入。
5. 正常 recovery 優先 Same Session，只補新 failure evidence/next action，不重複 Session 已知 Context。
6. Final AI validation 每次 run 使用獨立 Fresh Session；若設定 3 次，三次 Session 都必須不同。
7. Structured-output/Stage 驗證異常先做 bounded Same Session recovery，最多 2 次；仍失敗才 Fresh Session。
8. Fresh/Rebuilt Session 才提供完整且必要的 Goal、Current Task、Project-state instruction 與 Stage instruction。
9. Workflow topology 必須 declarative；普通 AI Stage 應能用 Stage preset + Prompt file 新增、移動或替換。
10. 能刪就刪、能合併就合併；現有架構能表達時不要新增另一層 service/helper/framework。
11. 可讀性是要求：名稱清楚、function cohesive、contract 明確、layer 少、不做隱藏魔法。
12. 移除 dead code、stale compatibility shim、舊流程名稱與無使用 alias；不要保留兩套相同 implementation。
13. 完整 AI task Prompt 固定 stdin；禁止把長 Prompt 放在 command-line argv。短 backend control command 不視為 task Prompt。
14. Folder、Python filename、class/function/field 命名必須描述真實責任；不要用 `common.py`、`helper.py`、`manager.py` 等模糊垃圾桶名稱取代合理分類。

核心：最少 Code、零 project hardcode、低耦合、可插拔、易擴充、可 Debug、24H 穩定。

## 修改前檢查
- 是否已有共用 helper/function 可以直接重用？
- 是否會產生第二套 parser/retry/path/snapshot/session/prompt implementation？如果會，先合併。
- Literal 是否只屬於某個 example/project？移出 Runner core。
- 這段 code 是當前 evidence 真正需要，還是預先猜未來？刪除 speculative code。
- Same-session Prompt 是否重送 Session 已知資訊？若是，改成 delta。
- Fresh/Rebuilt Session 是否擁有足夠 context 可以獨立延續？只補必要內容。
- Execute 是否仍只做 Current TODO？
- Deterministic Validator 是否驗 requirement，而不是 Planner 拆法？
- 是否新增 raw event type、Plugin implementation 或 backend-specific branch 到 Workflow？禁止。
- 真實行為變更後，中英文 docs 與 tests 是否同步？

## 共用入口
CLI/UI/Skill/Python 都應使用 `runner.api.RunRequest` / `runner.api.run()`；不要為 UI/Skill 再建立第二套 orchestration。

`runner/bootstrap.py` 是 composition root；Backend/Plugin registry 只在邊界組裝依賴。Workflow 不應自行 discover Plugin 或 Backend。

## UI／Extension 維護邊界
UI 是與 CLI 同層的 Adapter，不是 Workflow Plugin。Pipeline、StageExecutor、Stage、AI client、Workflow loader 都不得 import UI。外部 Stage／Backend 先透過 installed extension 在 Workflow validation 前註冊；runtime-only Plugin 之後才透過 Hook/Event boundary attach。新增外部 Stage 不得要求 Pipeline 增加 Stage-name branch。

可編輯 Workflow／Prompt 使用共用 atomic resource function 與 optimistic `expected_hash`；active Run 一律使用自己的 durable Workflow／Stage Prompt／Goal／Final-AI Prompt snapshot。UI 多 Run 優先採一個 Run 一個 worker process 做隔離，不要只為 UI 把全域 runtime 改造成複雜的 in-process concurrency。

## Project policy
所有維護中的 smoke/example project root 都應有 `.ai-task-runner.yaml`。Policy 本身自動 protected。Immutable input/reference fixture 應列成 protected；Task 本來要修改的檔案不可 protected。

Project 責任集中在：
- `runner/project/files.py`：manifest/change detection/restore/stale snapshot cleanup。
- `runner/project/policy.py`：project policy 與 protected path。
- `runner/project/instructions.py`：Runner-managed QWEN.md/AGENTS.md section。

## Current Task 執行契約
Fresh/Rebuilt Executor 收到 Current Task、Original Goal 作為 global context、必要 validator/review feedback 與完整 Stage instruction。正常 Same Session 已看過同一份 Stage Prompt contract 時，`continuation_prompt` 只補下一個 TODO 或新產生的 Review/Validator evidence；Recovery continuation 則更小，只帶 Stage identity、新 failure evidence、需要時的 readonly reminder 與下一步要求。
Recovery 需要更多 evidence 時，只補與 Current Task 直接相關的 previous attempt output 或 diagnostic，不得因此擴大 scope。

Current TODO 之外的後續 TODO 不應塞入 Execute prompt。Project filesystem 是目前實作真相；Resume 時先尊重已存在且有效的修改，不要無條件重做。

## Session / Recovery 契約
- Initial call：完整 Stage Prompt。
- Real failure：Same Session bounded retry，預設最多 2 次。
- Same Session 仍失敗：Fresh Session + 完整必要 Context。
- Fresh Session 出現相同 persistent failure：回傳 `replan`，重新建立 Plan。
- 不同 failure fingerprint：重新計數，不沿用舊 failure streak。Timeout identity 必須使用 backend 提供的穩定語意 recovery key，不可直接依賴會變動的 raw stderr；完整 stderr 只保留給 diagnostics。
- API/service transient failure：使用 AI transport backoff，不消耗 Stage failure budget；等待視窗用盡後由 canonical API resume durable state。
- Final AI voting：每個 validation run 都建立不同 Fresh Session。

## Validation 與 YAML List
Validator feedback 存入 state 時 bounded 到 20,000 characters，保留開頭與結尾。Runner 會為 Validator process 設定 `AI_TASK_RUNNER_WORK_DIR`；維護中的模板會把報告寫到其 `validator-reports/` 下，單獨執行時則 fallback 到 `.ai-task-runner`。External Validator（exe、bat、jar、Java CLI 等）應使用 `docs/validator_templates/external_command_validator.py`。

支援三種 validation：AI-only、Python-only、Mixed。Mixed 一律先 Python hard gate，再 Final AI voting。

YAML batch mode 已支援，並支援每筆獨立 `project_root`、`goal_file`、`workflow_file`、AI validation count/required passes。每筆使用自己的 nested state；runtime scope 必須在 child item 結束後恢復 parent，禁止全域 state leakage。

Workflow YAML 只保留兩個頂層 key：`stages` 定義可重用命名 node，`flow` 定義靜態頂層順序。`recover` 可以直接包含靜態 recovery Stage sequence；不再有 reusable-subflow、`expand` 或 `foreach` DSL。Registry 只保留 `type -> class`（預設 `base`、`plan`、`python`）；一般 AI-backed node 預設 `type: base`，可省略。`PlanStage` 是刻意的特殊 Stage：Loader 從 YAML 結構推導可用 dynamic Stage catalog，Plan 為每個 TODO 選擇 ordered Stage names，Pipeline 持久化並執行 `next_steps`；一般 Stage class 仍完全不知道 routing。

頂層 Stage 的有效 FAIL 或 recovery 用盡後需要回到目前／更前面的 Workflow 位置時，使用共用的 1-based YAML `restart_at`。Session recovery、Planning 產生的 child group 與 completion rule 應留在既有語意 owner，不做成任意 YAML topology。

## Prompt Contract
所有 bundled Stage Prompt 使用 Jinja + `StrictUndefined`。Top-level template variable 只能由 `runner/prompts/context.py` 提供，不得直接暴露 `RunState`、`RuntimeConfig`、`scratch` 等內部物件。

一般 AI 工作就是 `BaseStage` YAML instance；`type` 預設為 `base`，通常省略。真正的新行為只需一個帶 `spec_class` 的 Stage class、一次 `register_stage("type", Class)` 與 YAML instance；Loader、Pipeline 禁止增加 Stage-name-specific branch。

Stage 只實作一次獨立 attempt，並以 `StageResult` 回傳 facts；不得建構／呼叫另一個 Stage，也不得選擇具體 successor。State reduction 放在注入的 result handler，串接放在通用 Pipeline/routing data。

共通 Stage 執行能力由 `StageExecutor` 統一擁有，不得在各 Stage 內重寫。已註冊 Stage 的 spec 可依需要 expose `retry`、`retry_attr`、`skip_on_error`、`track_changes`、`tolerate_restored_changes`；AI-backed Stage 另外擁有 `fresh_session_on_start`、`fresh_session_each_run`、`prompt`、`parser` 等 Session／Prompt 能力。Routing-only 欄位（`recover`、`max_results`、`fresh_after_same_failures`、`restart_at`、`label`）屬於 `FlowNode`，建立 Stage 前會移除。`retry: 0` 表示不做 Same Session retry，錯誤會直接升級到既有 Fresh Session recovery；retry budget 為 0 時不允許 `skip_on_error`。

如果只是字串條件/format，優先用 Jinja；只有真正需要計算的 planning-specific context 才放在 `PlanStage`。

## Plugin / Event 邊界
Plugin 只處理 cross-cutting concern，例如 Console、Safety、History、Observability。Workflow 禁止 import 具體 Plugin。

Workflow 只使用 semantic progress API；raw event type/schema、subscriber delivery 屬於 runtime。Script batch orchestration 也透過同一 EventBus 發布 semantic `script.item_*` event；Console output、JSON Lines、callback 與 diagnostic log 只屬於 Plugin。不要在 Workflow 寫 `publish("runner.xxx", ...)`。

## Agent rule files
- Qwen Code：`QWEN.md`
- OpenCode：`AGENTS.md`

OpenCode 官方 project rule filename 是 `AGENTS.md`，不是 `AGENT.md`。

同一 process 內禁止只為 resume 既有 Session 而 new `AIClient`；應重用既有 client。只有 process restart 後的 `--resume` 可以從 durable `ai_session_id` 重建 client。

## 文件契約
所有 human-facing 維護文件必須提供英文 `.md` 與繁中 `.zh-TW.md` 對應版本，兩邊應描述同一套現行功能與章節。新增/刪除功能時必須同步更新兩個版本，不得只改 README 其中一邊。

Prompt resource、AI backend instruction file（`QWEN.md` / `AGENTS.md`）與 sample project task prompt 不屬於翻譯文件，因此不要求雙語 duplicate。
