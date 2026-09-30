# 自訂 Workflow

Workflow 是由 Stage 組成的 YAML graph。CLI、API、YAML List、Studio 都使用同一套 runtime。

## 最小結構

```yaml
stages:
  execute:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: execute

  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - review
  - final_validate
```

PASS 預設走 `flow` 的下一個 Stage。需要語意跳轉時只使用：

```yaml
routes:
  pass: another_stage
  fail: earlier_stage
```

target 也可使用 `done` 或 `stop`。

技術 ERROR 不是 graph edge。Exception、backend failure、timeout、transient API error 都由 `StageExecutor` 處理。需要時只設定：

```yaml
error_policy:
  retries: -1
```

目前 runtime 不支援 `routes.error`、repair/recover/restart_at/repeat/max_attempts/on_exhausted。

## Stage 類型

- `plan` — 產生 Task[]。
- `task` — 執行目前 Task。
- `review` — read-only 結構化完成度判斷。
- `ai_validator` — 獨立 AI 驗證，可多次投票。
- `base` — 通用 AI Stage。
- `handoff` — 每次動態選一個允許的下一個 Stage。
- `command` — 外部 command/Python tool。

自訂 Python Stage 只需要實作工作與結果；retry/session recovery 統一由 StageExecutor 負責。

## Dynamic Handoff

```yaml
stages:
  coordinator:
    type: handoff
    targets: [implementer, verifier, final_validate]
    session_policy: role

  implementer:
    type: base
    prompt: common/dynamic_worker.md
    instructions: Implement the smallest correct change.
    session_policy: role
    mode: write
    track_changes: true
    routes:
      pass: coordinator

  verifier:
    type: base
    prompt: common/dynamic_worker.md
    instructions: Independently verify tests and evidence.
    session_policy: role
    readonly_safety: observe
    routes:
      pass: coordinator

  final_validate:
    type: ai_validator
    validator: ai
    session_policy: fresh
    routes:
      pass: done
      fail: coordinator

flow:
  - coordinator
  - implementer
  - verifier
  - final_validate
```

Handoff 只決定下一個 target；所有角色仍是普通 Stage。Discussion / review board / triage 應用同一個 Dynamic Handoff pattern 表達，不新增第二套 runtime。

## Session Policy

- `role`：Stage name 擁有 durable 可重用 Session，可跨後續 handoff 與 process resume；Dynamic specialist 預設使用。
- `main`：共用 Runner 主 Session。
- `fresh`：每次 invocation 都是新 Session；獨立驗證建議使用。
- `auto`：built-in/internal 預設行為；只有 `auto` 可搭配 `session_key`。

角色 Session 若連續發生技術錯誤，可只替該角色切換 fresh Session；其他角色 Session 不受影響。

## 多次執行 / 投票

```yaml
review_vote:
  type: review
  session_policy: fresh
  runs: 3
  required_passes: 2
```

## Task Scope

`scope: task` 的 Stage 必須形成一段連續 block，會針對目前 Task 執行。Validator 不可設為 task scope。

## Command Stage

```yaml
validate_file:
  type: command
  result_kind: validation
  command: ["{python}", "validator.py", "--project-root", "{project_root}"]
  routes:
    fail: execute
```

若自訂 command/Python Stage 要直接產生 Task[]，可使用 `produces: tasks`，不一定需要 PlanStage。

## Prompt

Prompt 使用 category-relative reference：

- `common/<name>.md`
- `ralphy/<name>.md`
- `workflow/<workflow-name>/<name>.md`

Dynamic 一般角色預設共用 `common/dynamic_worker.md`，角色差異寫在 `instructions`。只有真正需要不同 protocol/tool contract 的角色才拆獨立 Prompt。

## 測試

Live 前先跑 deterministic dry-run：

```powershell
python tool/workflow_dryrun.py path/to/workflow.yaml --matrix --json
```

單一 Stage 可使用 Workflow Studio Stage Test 或 `tool/stage_probe.py`。

real backend gate 與 CI 分開：

```powershell
tool\qwen_live_reliability_0_5h.bat
```

短 gate PASS 後再跑 24H。
