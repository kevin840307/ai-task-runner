# 自訂 Workflow 指南

版本：1.2.61

這份文件示範目前最新的 Workflow 寫法。優先使用語意化 Stage type，YAML 只保留真正會改變 SOP 的設定，不要再複製舊版 implementation detail。

## 1. 一般線性 Workflow

Workflow 不一定需要 Plan，也不一定需要 Validator。單純線性流程只寫真正需要的 Stage：

```yaml
stages:
  build:
    type: task
    prompt: prompts/build.md

  smoke:
    type: command
    command: "{python} -m pytest -q"

flow:
  - build
  - smoke
```

只要明確指定自訂 Workflow，而且該 Workflow 本身沒有 Validation Stage，`validator` 可以省略。

## 2. Plan 產生 TODO 的 Workflow

`PlanStage` 是內建 AI Task Producer；每個 TODO 要怎麼跑仍由 Workflow 決定：

```yaml
stages:
  planning:
    type: plan

  execute:
    type: task

  review:
    type: review
    recover: [repair]

  repair:
    type: task

  validate_file:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"

flow:
  - planning
  - validate_file
```

頂層 `PlanStage` 會自動讓每個 TODO 依序執行標準 `execute -> review` SOP。只有需要覆寫預設（例如 Review recovery）時才需要定義 `execute` / `review`；顯式 `scope: task` 仍保留給非 Plan Producer 或刻意自訂的逐 TODO SOP。

## 3. Python Stage 也能產生 Task[]

任何 Stage 都可以用 `produces: tasks` 回傳公開 Task JSON contract：

```yaml
stages:
  discover_tasks:
    type: command
    command: "{python} custom_task_producer.py"
    produces: tasks

  execute:
    type: task

  review:
    type: review
    recover: [repair]

  repair:
    type: task

flow:
  - discover_tasks
  - stage: execute
    scope: task
  - stage: review
    scope: task
```

Producer 將合法 JSON 寫到 stdout：

```json
{
  "tasks": [
    {
      "title": "Implement feature",
      "description": "Make the requested focused change.",
      "deliverable": "The requested behavior works.",
      "acceptance_criteria": ["Relevant verification passes."]
    }
  ]
}
```

Runner 自己產生 durable Task ID；Producer 不應該輸出 Stage name 或 Workflow topology。

可直接參考：

- `examples/custom_workflow_latest.yaml`
- `examples/custom_task_producer.py`

## 4. 同一 Stage 搭配不同 Prompt 重用

Stage definition 可以重複使用，flow invocation 再覆寫 prompt：

```yaml
stages:
  run_prompt:
    type: task

  review:
    type: review

flow:
  - stage: run_prompt
    prompt: prompts/design.md
  - stage: review
    prompt: prompts/review_design.md
  - stage: run_prompt
    prompt: prompts/implementation.md
  - stage: review
    prompt: prompts/review_implementation.md
```

## 5. Python 與 Command Stage

User/Project Python 使用 `command`，不會 import 進長時間 Runner process：

```yaml
check:
  type: command
  command: "{python} stages/check.py --mode strict"
```

一般外部 argv command 使用：

```yaml
test:
  type: command
  command: "{python} -m pytest -q"
```

`command` 是 Python script、File Validator 與任意 argv 唯一的 process execution boundary。

## 6. Recovery 與 Repeat

Recovery 仍保持簡單的宣告式寫法：

```yaml
review:
  type: review
  recover: [repair]

flow:
  - stage: review
    repeat: 3
```

`restart_at` 可以跳回自己或更早的 top-level Stage。`type: review` 已經有 semantic-failure 預設門檻，所以一般不需要再寫 `fresh_after_same_failures`；只有真的要 override policy 時才設定。

## 7. YAML Task List Mode

每一筆 Task 仍可有不同 Project、Validator、Validator 參數與 Workflow：

```yaml
- goal_file: projects/a/prompt.md
  project_root: projects/a
  validator: projects/a/validation.py
  validator_args: [--env, A]

- goal_file: projects/b/prompt.md
  project_root: projects/b
  workflow_file: workflows/custom.yaml
```

若該 item 明確提供 `workflow_file`，`validator` 可以省略；若沒有 explicit Workflow，則仍需要 `validator`，Runner 才能選擇內建 File / AI / Mixed Workflow。

## 8. UI / AI 生成 Workflow

外部 UI 不需要 import Runner internals，直接把檔案格式與 JSON tool output 當 boundary：
Runtime monitoring 也可以完全不 import Runner module：detached local UI 唯讀 configured work directory 的 `state.json` 顯示目前狀態，並讀 `stream.log` 顯示最近 bounded subprocess output。這些 monitoring file 都是 read-only，不取代 execution API 或 Workflow validation tool。


```text
Generate/Edit YAML
    -> workflow_catalog.py
    -> production loader validation
    -> workflow_dryrun.py --json
    -> publish
```

可用：

```bash
python tool/workflow_catalog.py
python tool/workflow_dryrun.py path/to/workflow.yaml --json
```

Prompt 繼續是 Markdown，User Python Stage 仍是普通 `.py` 檔，因此 UI 可以 CRUD Workflow / Prompt / Python Stage，而完全不 import Pipeline 或 StageExecutor。

### Command 語法

`command` 可使用單行字串或 argument list。一般命令優先使用字串，例如 `command: "{python} D:/validation.py --asd sss"`；只有 argument boundary 或巢狀 quoting 較複雜時才使用 list。`result_kind: validation` 會把 command 定義成外部 validation gate；validation command 預設清除 `validator-reports`，若明確設定 `clean_work: []` 則關閉此清理。
