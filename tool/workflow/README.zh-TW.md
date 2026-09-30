# Workflow 工具範例

這些 YAML 是目前 Workflow runtime 的 deterministic 範例，也會被 dry-run / live reliability preflight 使用。

## 範例

- `01_default_ai.yaml` — Plan -> Task -> Review -> Final AI Validator。
- `02_ai_with_review_gate.yaml` — 在最終驗證前增加一個獨立 fresh Review gate。
- `03_file_validation.yaml` — Task flow + command/File Validator。
- `04_mixed_with_review_gate.yaml` — 獨立 Review + File Validator + Final AI Validator。
- `05_review_vote_3_choose_2.yaml` — 三次 fresh Review，2/3 PASS 才通過。
- `06_custom_task_producer.yaml` — command-backed 自訂 Task producer，證明不一定需要 PlanStage。
- `11_multi_validators_anywhere.yaml` — Validator 與一般 Stage 可交錯，驗證 Validator 不限定只能放最後。

## 目前 Workflow 契約

Workflow 只有 Stage 與語意結果 routing：

```yaml
stages:
  execute:
    type: task
    routes:
      fail: execute

  verify:
    type: review
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - verify
```

Graph edge 只支援 `routes.pass` / `routes.fail`。技術例外、timeout、API/backend error 由 `StageExecutor` 負責，使用 `error_policy.retries` 或全域 `stage_retries`。目前沒有 `routes.error`、repair Stage、recover edge、restart_at、repeat、max_attempts 或 on_exhausted graph 契約。

Dynamic Handoff 使用一個 Handoff Stage 搭配多個候選 target：

```yaml
coordinator:
  type: handoff
  targets: [implementer, verifier, final_validate]
```

每次 Handoff 只動態選一個 target，實際角色仍然都是普通 Stage。

## Session Policy

AI-backed Stage 可選：

- `session_policy: role` — 由 Stage name 擁有的 durable 可重用 Session；Dynamic specialist 預設使用。
- `session_policy: main` — 共用 Runner 主 Session。
- `session_policy: fresh` — 每次 invocation 都新建 Session；適合獨立最終驗證。
- `session_policy: auto` — 內部/預設 Stage 行為；只有 `auto` 可以搭配 `session_key`。

可重用 role Session 若連續發生技術錯誤，StageExecutor 可以只替該 Stage 切換到 fresh Session，成功後再持久化新的 Session。

## 驗證與測試

Deterministic dry-run：

```powershell
python tool/workflow_dryrun.py tool/workflow/11_multi_validators_anywhere.yaml --matrix --json
```

real-Qwen reliability tool 在 live model probe 前會先跑代表性 dry-run preflight：

```powershell
tool\qwen_live_reliability_0_5h.bat
```

短 gate PASS 後再執行 `tool\qwen_live_reliability_24h.bat`。
