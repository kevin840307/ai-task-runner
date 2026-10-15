# Workflow Studio

Workflow Studio 是正式 YAML Workflow 的 UI editor，CLI/API/runtime 都使用同一份模型，不存在第二套 graph schema。

## Assets

Global：

```text
runner/assets/workflows/*.yaml
runner/assets/prompts/<category>/*.md
```

Project：

```text
<project>/.ai-task-runner/assets/workflows/*.yaml
<project>/.ai-task-runner/assets/prompts/<category>/*.md
```

`.ai-task-runner.yaml` 是 project policy/config，不是 Workflow。

## Full Designer

React Flow 畫面會顯示：

- START / END：只存在 UI 的 virtual node；
- 每一個 YAML Stage = 一顆真實 node；
- 一般 Stage 使用 PASS / FAIL handle；
- `type: handoff` 使用一個 HANDOFF handle 連多個允許 target；
- `scope: task` 顯示為 visual group；
- ERROR retry 是 Stage 設定，不是 edge。

Dynamic Handoff targets 預設橫向單排；畫布可平移、縮放、手動拖曳。手動位置只存在瀏覽器 UI state，不改變 YAML runtime 語意。

## Stage 參數

Inspector 由 `/api/workflow/catalog` 動態產生。

主要分區為 Content、Execution、Result、Advanced，runtime catalog 已提供的預設值不在 UI 重複硬編碼。

Session policy：

- `role`：durable 可重用的 Stage-owned Session；
- `main`：Runner 主 Session；
- `fresh`：每次 invocation 新 Session；
- `auto`：built-in/default 行為。

從 `auto` 切到明確 policy 時，Studio 會移除衝突的舊 session 欄位。`session_key` 只在 `auto` 顯示；內部 `fresh_session_each_run` / `fresh_session_on_start` 不再當成一般 UI 設定。

## Routing

一般 graph routing 只有 PASS / FAIL：

```yaml
routes:
  pass: some_stage
  fail: earlier_stage
```

PASS 可到 `done`，FAIL 可到 `stop`；回到前面 Stage 就是 rollback/loop。

Handoff routing 儲存在：

```yaml
targets:
  - implementer
  - verifier
  - final_validate
```

ERROR 只設定 `error_policy.retries` 或全域 retry。Review 若設定有限 local retry，Full Designer 會明確顯示 `retry -> Skip`；其他 Stage 的有限 retry 用盡仍 fail-closed。UI 不支援 ERROR edge、repair/recover/restart_at/repeat/max_attempts/on_exhausted。

## Stage Test

Test tab 只在隔離 temporary Project 執行目前選中的一顆 Stage，使用尚未 Save 的 graph draft，回傳：

- status；
- output / structured data；
- changed files；
- resolved next target。

不會繼續跑後面的 Workflow，也不修改真實 project/YAML。

## Save

YAML 是唯一 canonical model。Graph Save 會先用目前 Workflow schema 驗證整份 draft，再一次 atomic write；非法 target/options/session-policy 組合不會部分寫入。

React/Vite source 在 `ui/studio-src`；編譯後 static assets 在 `ui/static/workflow-studio-app`，由既有 Python UI server 提供，使用者端不需要 Node.js。

## Runtime Status

UI 只透過正式 runtime/state/control contract 判斷執行狀態，不應因 stale UI state 把 idle project 顯示成 running。Stop/resume 也沿用 Runner control contract。

## 測試

主要 coverage：

- graph save/round-trip/validation；
- Stage CRUD 與 asset roots；
- Handoff handles/targets/layout；
- session-policy normalization；
- Stage Test sandbox；
- browser CRUD；
- static source/bundle contract；
- CI React Studio build。


## 產品工作區

執行 `python ui/main.py` 時預設開啟 `/chats.html`。舊的 `/` 工作區仍保留為相容／runtime 介面；新的產品 shell 分成三層 scope：Global navigation（Chats / Library / Settings）、各 domain 的 context sidebar，以及 main content。

### Chats

每個 Chat 都有固定、由 UI 擁有的 `chat_id` 與 root path。Chat metadata 與 transcript 儲存在 UI data store，不會寫進 Runner `state.json`。Chat 可以 Archive，但不會刪除其 Tasks 或歷史；原路徑遺失時歷史仍可讀，但不能再開始新工作。

一般 Chat 對話透過已註冊 Backend 的 bounded、唯讀 project-access adapter 執行。Fresh backend session 會取得 bounded durable conversation context；同一 session 的 follow-up 只送新的訊息。Chat 不會建立 Workflow run、Stage state、retry loop 或 Runner control state。

### Tasks 與 Task Detail

Task 有 durable、由 UI 擁有的 identity 與 execution references，但 live status 一律投影自既有 Runner runtime。同一 canonical filesystem execution path 同時間最多只能有一個 Active Task；瀏覽器 disabled state 只是 UX，真正權威仍是 backend/runtime ownership guard。

常用 New Task 表單只直接顯示 Type、Instruction、可選 Title、Workflow 與 Run。Goal file、Backend/Model 與 workspace isolation 都屬於 secondary/advanced 選項。開始執行前，resolved Workflow、prompt source、Backend/Model 與 workspace 會凍結到既有 Runner request/script input。

Task Detail 的 Stop / Resume / Rerun / Continue 可用性來自 canonical runtime projection 與目前 path availability。Path 被後續 Task 重用前，terminal execution evidence 會先保存到 bounded Task history，因此舊 Task 不會誤讀新的 `state.json`。Delete Task 只刪 UI-owned Task record，不執行任何 Git integration。

### Task List

Task List 是既有 YAML List/script runner 的 UI adapter，不是瀏覽器端 scheduler。Visual items 支援新增／刪除／複製／重排、goal-file input、繼承或 item-level Workflow，以及 Advanced YAML view。Visual/YAML 轉換會走與 CLI 相同的 `runner.script` parser 驗證，並保留所有已支援的 advanced fields。

Stop 與 Resume 仍使用既有 script runtime action。UI 只投影 current item pointer 與 child evidence，不會自行啟動下一個 item。

### Library 與 Settings

`/library.html` 是全域 reusable-asset domain，明確顯示 Workflow / Prompt 的 Global 或 Project scope，並開啟既有 Full Designer / Prompt Editor。New Task 的 Workflow picker 重用同一份 catalog 與 visibility metadata。

`/settings.html` 只管理介面偏好；Runner、Workflow、Stage 與 Task execution 設定仍由原本 owner 管理。

### Worktree isolation

Main 永遠是預設 Task workspace。Git project 的 Task form 另外可以提供 New Worktree 或既有 worktree。每個 worktree 都是獨立 canonical execution path，因此也是獨立 ownership domain。

Task-created worktree cleanup 必須明確操作且 fail-closed：Active Task 不可 cleanup、先 archive runtime evidence、dirty worktree 不會被 force-remove，而且 branch 會保留。Task execution 永遠不會自動 merge、rebase、cherry-pick 或處理 integration conflict。

## 產品工作區測試

重要 coverage 包含：

- `tests/test_chat_turn.py`：bounded Fresh/Same Session 唯讀 Chat 行為；
- `ui/tests/test_chat_index.py`、`test_chat_messages.py`：durable Chat identity/transcript 與 archive/path guards；
- `ui/tests/test_task_index.py`、`test_task_workspace_state.py`：durable Task history、terminal evidence 與 historical rerun；
- `tests/test_script_project_root.py`：共用 YAML List parsing、inheritance 與 CLI compatibility；
- `ui/tests/test_task_worktree.py`：明確、不可自動 merge 的 worktree lifecycle；
- `ui/tests/test_future_workspace_browser.py`：Chat → Task / Task List → canonical action browser flow。
