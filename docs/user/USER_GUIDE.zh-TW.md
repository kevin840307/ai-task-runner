# 使用指南

## 執行單一任務

CLI、API、UI、YAML List 都使用同一套 Workflow runtime。

常用 CLI：

```powershell
python ai_task_runner.py --goal-file prompt.md --project-root . --validator ai
```

需要指定 Workflow 時使用 `--workflow`。Linear 或 Dynamic Handoff 是由 Workflow YAML 決定，不另外增加 execution-mode selector。

## Runtime 模型

Workflow 是 Stage 清單。

- PASS 預設走下一個 Stage。
- FAIL 預設停止，除非 `routes.fail` 指定其他 Stage。
- PASS/FAIL 可回到前面 Stage，形成 rollback/loop。
- ERROR 只代表技術錯誤；StageExecutor 負責 retry / session rebuild，重試用盡就停在目前 Stage。
- 沒有 repair/recover/restart_at/repeat/max_attempts/on_exhausted graph 模型。

## Plan 與 Task Scope

`type: plan` 產生 Task[]。逐 Task 工作由 YAML 顯式定義一段連續 `scope: task`：

```yaml
stages:
  planning:
    type: plan

  execute:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: execute

flow: [planning, execute, review]
```

自訂 `command` / Python Stage 也能用 `produces: tasks`，所以不一定要 PlanStage。

## Validation

File validation 通常是 `command` + `result_kind: validation`。AI validation 使用 `type: ai_validator`、`validator: ai`。

Validator 是普通 top-level Stage，可以放在 flow 中間或最後，但不能設 `scope: task`。

獨立 Final AI Validation 建議：

```yaml
session_policy: fresh
```

多次投票：

```yaml
runs: 3
required_passes: 2
```

## Dynamic Handoff

Dynamic Handoff 是唯一 multi-agent runtime primitive。

```yaml
coordinator:
  type: handoff
  targets: [requirements, architect, implementer, verifier, final_validate]
  session_policy: role
```

Coordinator 每次只選一個 target。各 specialist 仍是普通 Stage，通常 PASS 後回 coordinator。

內建 Dynamic specialist 預設使用 `session_policy: role`；最終獨立驗證使用 `fresh`。

### Session Policy

- `role`：每個 Stage name 一個 durable 可重用 Session，可跨 process resume。
- `main`：使用 Runner 主 Session。
- `fresh`：每次 invocation 都重新開始 Session。
- `auto`：built-in/internal 預設；只有 `auto` 可搭配 `session_key`。

Role Session 若連續技術失敗，StageExecutor 只替該 role 切到新 Session，其他 role 不受影響。

## Retry / 技術錯誤

全域預設：

```text
stage_retries = -1
retry_delay = 5
retry_max_delay = 300
```

Stage 可以只覆寫 retry 次數：

```yaml
error_policy:
  retries: 2
```

HTTP 429/502/503 等 classified transient backend error 會 delay/backoff，不改變 graph position。

## YAML List

`--script tasks.yaml` 會依序執行多筆 item。每個 child 都有自己的 durable state，仍使用同一套 WorkflowRunner/FlowEngine/StageExecutor/StateStore。

每筆可覆寫 Workflow、backend/agent/validator args、project root、timeout、retry、max_cycles/skip_on_max_cycles、Final AI quorum。Resume/work-dir 等 batch ownership 設定屬於外層。

## max_cycles

`max_cycles` 限制 semantic backward graph cycle，`-1` 表示不限制。YAML List 可搭配 `skip_on_max_cycles` 在 child 超過 cycle limit 後繼續下一筆。

Dynamic role -> coordinator 也是 backward route，因此有限 `max_cycles` 也會限制 Handoff loop 次數；需要長時間 Dynamic 工作時維持 `-1`。

## Read-only Safety

Review/Validation 等 read-only Stage 可使用 `readonly_safety: observe`。Safety/change tracking 由 StageExecutor/hooks 負責，不屬於 routing。

## Protected Files

穩定規則建議放 project policy，也可使用 `--protect-file`。已知 cache/build/test-output 等 runtime technical artifact 會和真正 source/project 變更分開處理。

## Resume / Diagnostics

Committed progress 儲存在 `.ai-task-runner` runtime state。Resume 會還原 workflow position、task position、上一個 transition evidence、主 Session ID、durable role Session ID。

常用診斷：

- runtime state；
- Runner event/log；
- `stream.log`；
- `debug/current-prompt.txt`；
- `debug/last-prompt.txt`；
- `debug/last-result.txt`；
- bounded debug history。

## Workflow Studio

Studio 直接編輯相同 YAML。Full Designer 支援 PASS/FAIL/Handoff edge、Stage parameter、Dynamic targets 排版與單積木 Test。

ERROR 不是 edge。Session policy 使用 `auto/main/role/fresh`，Studio 會防止與 `session_key` 衝突。

## Deterministic / Live 測試

Deterministic：

```powershell
python -m pytest -q
python tool/workflow_dryrun.py runner/assets/workflows/dynamic_handoff.yaml --matrix --json
```

短 real-Qwen gate：

```powershell
tool\qwen_live_reliability_0_5h.bat
```

短 gate PASS 後再跑：

```powershell
tool\qwen_live_reliability_24h.bat
```

Deterministic CI 綠燈不等於 real backend 或 24H 已驗證。
