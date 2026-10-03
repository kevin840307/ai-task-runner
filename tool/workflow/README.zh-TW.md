# Workflow 工具範例

這些 YAML 是目前 Workflow runtime 的 deterministic 範例，也會被 dry-run / live reliability preflight 使用。

## 範例

- `01_default_ai.yaml` — Plan 在 runtime 自己展開 Execute -> Review child Workflow，完成後進 Final AI Validator。
- `02_ai_with_review_gate.yaml` — Plan children 後再加一個獨立 fresh AI Review profile 與 final validation。
- `03_file_validation.yaml` — Plan children 後執行 command/File Validator。
- `04_mixed_with_review_gate.yaml` — Plan children + 獨立 Review + File Validator + Final AI Validator。
- `05_review_vote_3_choose_2.yaml` — AI Review profile 執行三次，2/3 PASS 才通過。
- `06_custom_task_producer.yaml` — command-backed 自訂 Task producer，由腳本自己定義 Tasks 與 child Stages。
- `11_multi_validators_anywhere.yaml` — Validator 與一般 Stage 可交錯。

## 目前 Workflow 契約

一般 AI 行為統一使用 `type: base` + profile：

```yaml
stages:
  execute:
    type: base
    profile: execute

  verify:
    type: base
    profile: review
    session_policy: fresh
    routes:
      fail: execute

flow:
  - execute
  - verify
```

舊的 `type: task`、`type: review`、`scope` 已移除。

Graph edge 只有 `routes.pass` / `routes.fail`。技術 exception、timeout、API/backend error 由 `runner/workflow/stage_executor.py` 的 StageExecutor 負責，使用 `error_policy.retries` 或全域 `stage_retries`。

## Dynamic child Workflow

任意 producer 都可以回傳 `tasks` 或 `stages`，但 child Stage definitions 必須由 producer 自己提供。Runner 只負責驗證、namespace、持久化、執行，完成全部 children 後才回 parent 下一個 Stage；Runner 不推測 child 結構。

目前 PlanStage 自己固定產生：

```text
Execute -> Review -> Execute -> Review -> ...
```

自訂 producer 範例則示範其他 producer 可以產生自己的 child graph。

## Dynamic Handoff

```yaml
coordinator:
  type: handoff
  targets: [implementer, verifier, final_validate]
```

每次 Handoff 只選一個允許 target。

## 驗證與測試

```powershell
python tool/workflow_dryrun.py tool/workflow/11_multi_validators_anywhere.yaml --matrix --json
tool\qwen_live_reliability_0_5h.bat
```

短 gate PASS 後再執行 `tool\qwen_live_reliability_24h.bat`。
