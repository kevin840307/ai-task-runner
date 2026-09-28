# Workflow 範例

這些 YAML 是目前 Runner contract 的精簡參考 graph。

現有範例：

- `01_default_ai.yaml`：Planning -> task-scoped Execute/Review -> AI Validator。
- `02_ai_with_grill.yaml`：增加一次 whole-result Review/Grill gate。
- `03_file_validation.yaml`：固定 File Validator。
- `04_mixed_with_grill.yaml`：Grill + File Validator + Final AI Validator。
- `05_grill_vote_3_choose_2.yaml`：3 個 Fresh Grill Session，至少 2/3 PASS。
- `06_custom_task_producer.yaml`：Command 產生 Task[]，搭配明確 task-scoped Execute/Review。
- `11_multi_validators_anywhere.yaml`：多個 Validator 與一般 Stage 交錯。

## Graph 規則

一個 `stages.<name>` 就是一個 node；`flow` 只放依序執行的 Stage 名稱。

Rollback / Loop 就是一般 result edge：

```yaml
stages:
  work:
    type: task
    scope: task

  review:
    type: review
    scope: task
    routes:
      fail: work

flow:
  - work
  - review
```

只使用 `routes.pass`、`routes.fail`、`routes.error`。Technical retry / Session recovery 是 Runner 全域行為，不寫進 Workflow YAML。

## Grill

Grill 不需要新 Stage type，直接重用 `type: review`：

```yaml
grill:
  type: review
  prompt: ../../runner/workflows/grill.md
  fresh_session_on_start: true
  routes:
    fail: planning
```

若需要多個獨立意見，使用一般 Stage vote 欄位：

```yaml
runs: 3
required_passes: 2
fresh_session_each_run: true
```

## Task Producer

`plan` 是內建 Task Producer。自訂 Stage 也可用：

```yaml
produces: tasks
```

產生 Task[]。逐 Task SOP 必須用連續的 `scope: task` nodes 明確表示；不存在 hidden Task/Review/Repair Stage。

## Validator

`result_kind: validation` 的 Command Stage 與 `type: ai_validator` 都只是一般 graph node。Semantic FAIL 要閉環時，直接用 `routes.fail`。
