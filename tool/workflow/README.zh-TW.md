# Workflow 範例

這些檔案是參考 YAML，不是 system workflow。可以複製到 custom workflow 區後再依需求調整。

- `01_default_ai.yaml`：一般自動化 Plan，使用內建 Task/Review/Repair lifecycle，再進 AI Validation。
- `02_ai_with_grill.yaml`：Final AI Validation 前增加一次獨立 Grill。
- `03_file_validation.yaml`：固定 Python/File Validator。
- `04_mixed_with_grill.yaml`：Grill + File Validation + Final AI Validation。
- `05_grill_vote_3_choose_2.yaml`：3 個 Fresh Grill Session，至少 2/3 PASS。
- `06_custom_task_producer.yaml`：Command 產生 Task[]，搭配明確 `scope: task`。
- `07_minimal_plan_only.yaml`：最小 Plan workflow，不含 final validator。
- `08_bounded_grill_continue.yaml`：Grill 最多 3 次；前兩次 FAIL 會修復，第 3 次仍 FAIL 就放行。
- `09_bounded_grill_fail_closed.yaml`：同樣最多 3 次，但耗盡後停止。
- `10_bounded_gate_reentry_reset.yaml`：bounded recovery 是通用 FlowNode 能力；往下後若再 restart 回 gate，重新從第 1 次計算。
- `11_multi_validators_anywhere.yaml`：多個 File + AI Validator 可和一般 Stage 交錯，Validator 後面也可以繼續放普通 Stage。

## 通用 Grill

Grill 不新增 Stage type，直接重用 `type: review`、既有 parser/output contract 與 recovery feedback：

```yaml
grill:
  type: review
  prompt: ../../runner/prompts/stages/grill.md
  fresh_session_on_start: true
  retry: 0
  recover: [repair_plan]
```

## Bounded semantic recovery

```yaml
grill:
  type: review
  recover: [repair_plan]
  max_attempts: 3
  on_exhausted: continue
```

語意：

```text
Grill #1 FAIL -> Repair -> Grill #2
Grill #2 FAIL -> Repair -> Grill #3
Grill #3 FAIL -> 不再 Repair -> Continue
```

若任一次 PASS 就直接往下並清除計數。只要已經往下，之後流程若又回到 Grill，會重新從 #1 計算。Technical `ERROR` 不算在這個 semantic FAIL 次數內。

`max_attempts` / `on_exhausted` 都是 optional；沒有 `max_attempts` 時完全維持原本行為。`on_exhausted` 可用 `continue` 或 `fail`；省略時預設為 `fail`。`max_attempts` 必須搭配 `recover`，也不能和 `repeat` 同時使用。

注意：這裡是 **Workflow FlowNode 層級**的 `max_attempts`；CLI/API 同名參數是 Same Session backend recovery budget，兩者用途不同。

## Plan 內建 TODO lifecycle

一般 `type: plan` 會在 Runner 內部執行 Task -> Review -> Repair（FAIL 時）-> Review，不依賴 YAML 裡叫做 `execute`、`review`、`repair` 的 Stage。若要自訂逐 TODO SOP，請在 Task Producer 後明確宣告連續的 `scope: task` nodes。

## 多 Validator

`result_kind: validation` 的 command Stage 與 `type: ai_validator` 都是一般 top-level gate；可以在 `flow` 任意位置放多個、和一般 Stage 交錯，每個 Validator 也可以有自己的 `recover`。
