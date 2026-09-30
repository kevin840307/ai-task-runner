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

ERROR 只設定 `error_policy.retries` 或全域 retry。UI 不支援 ERROR edge、repair/recover/restart_at/repeat/max_attempts/on_exhausted。

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
