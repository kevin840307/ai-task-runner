# 自訂 Workflow 指南

版本：1.2.64

這份文件示範目前最新的 Workflow 寫法。優先使用語意化 Stage type，YAML 只保留真正會改變 SOP 的設定，不要再複製舊版 implementation detail。

## Custom asset 資料夾

建議把「Ownership」與「用途分類」分開：`system/` 由 Runner 管理且唯讀；使用者資產都放在 `custom/`，再依用途細分。內建可重用範例目前放在 `custom/common`；領域專用資產可放 `custom/e2e`、`custom/regression`，也支援更深層子資料夾。

```text
runner/workflow/
├─ system/
└─ custom/
   ├─ common/
   └─ e2e/

runner/prompts/
├─ system/ + stages/
└─ custom/
   ├─ common/
   └─ e2e/
```

Workflow Studio 會遞迴發現所有 Custom Workflow/Prompt，左側清單會依資料夾形成可獨立收合的 Folder Group；Search 仍會跨所有資料夾搜尋，搜尋時會直接顯示符合結果的群組。新增 Workflow/Prompt 時也可以選擇或建立 Custom 子資料夾。

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

頂層 `PlanStage` 會自動讓每個 TODO 依序執行內建 `Task -> Review -> Repair（FAIL 時）-> Review` lifecycle。Planning 維持 read-only，且預設採「需要才讀」：AI 可以從 host account 可讀取的任何 path（包含目前 Project 之外）讀取最小且相關的 evidence，但不要求規劃前一定掃檔。若顯式設定 `allow_project_read: false`，就會關閉 Planning 的讀檔能力；欄位名稱為了相容既有 YAML 保留不改。Plan 的內建 lifecycle 與 YAML Stage 名稱無關，不會再依名稱尋找 `execute`、`review` 或 `repair`。若要自訂逐 TODO SOP，請在 Plan（或其他 Task Producer）後明確宣告連續的 `scope: task` block。

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

### 限制 FAIL -> recover -> retry 次數

任何 FlowNode 都可以選擇性加入 bounded semantic recovery：

```yaml
flow:
  - stage: grill
    recover: [repair_plan]
    max_attempts: 3
    on_exhausted: continue
```

`max_attempts` 計算的是該 FlowNode 回傳已成功解析之 semantic `FAIL` 的執行次數。第 1 到 N-1 次 FAIL 會先跑 `recover`，再重跑原 Stage；第 N 次仍 FAIL 時不再執行 recovery。`on_exhausted: continue` 直接往下一個 FlowNode；`on_exhausted: fail` 則停止。若有設定 `max_attempts` 但省略 `on_exhausted`，安全預設值是 `fail`。只要 PASS 就清除計數。Stage 已成功往下後，若後續 routing 又 restart/re-entry 回來，視為新的 gate cycle，從 attempt 1 重新計算。Technical `ERROR` 不會消耗這個 semantic attempt budget。

這兩個欄位都是 optional。沒有設定 `max_attempts` 時，**完全維持原本 recovery 行為，不會偷偷增加上限**。`on_exhausted` 只能搭配 `max_attempts`；`max_attempts` 必須有 `recover`，且不能在同一個 FlowNode 和 `repeat` 或 `restart_at` 同時使用。

> YAML FlowNode 的 `max_attempts` 和 CLI/API 的 `max_attempts` 是不同 scope。CLI/API 參數控制 Same Session backend recovery；這裡的 YAML 參數只限制單一 FlowNode 的 semantic `FAIL -> recover -> retry` gate cycle。

### Recovery / retry YAML 參數對照

| 參數 | Scope | 用途 |
| --- | --- | --- |
| `retry` | Stage execution | 單次 Stage execution 內的 technical/error retry budget；不是 semantic FAIL recovery。 |
| `runs` | Stage execution | 同一次進入 Stage 時執行多次，常用於獨立 voting。 |
| `required_passes` | Stage execution | `runs > 1` 時至少需要幾次 PASS。 |
| `recover` | FlowNode routing | semantic FAIL 後先執行哪些 recovery Stage，再回原 FlowNode。 |
| `repeat` | FlowNode routing | 既有 bounded-recovery 行為，為相容保留；不要和 `max_attempts` 同時使用。 |
| `max_attempts` | FlowNode routing | 單一 gate cycle 最多允許幾次 semantic FAIL attempt；省略時完全維持既有行為。 |
| `on_exhausted` | FlowNode routing | `max_attempts` 耗盡後用 `continue` 放行或 `fail` 停止；預設 `fail`。 |
| `fresh_after_same_failures` | FlowNode/session policy | 同一 semantic failure 重複 N 次後，把該 Stage 切到 Fresh Session。 |
| `restart_at` | FlowNode routing | FAIL 時跳回指定的同一個或更早 top-level Stage。 |

`max_attempts` 算的是 Gate 執行次數，不是 Repair 次數。`max_attempts: 3` 代表最多只會跑兩次 recovery；第 3 次 FAIL 就視為 exhausted。

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

### Visual Editor 支援

Workflow Studio Visual mode 已提供常用 Stage 與 Flow routing 控制，包括 `max_attempts`、`on_exhausted`、`runs`、`required_passes`。Recovery 參數以分組與 Behavior 摘要呈現，不在每個欄位下重複長說明。`continuation_prompt` 仍刻意保留為 YAML-only advanced override。

## Ralphy-style：Fresh Task + 必過 AI Validation

內建 Custom 範例 `runner/workflow/custom/common/ralphy_ai_validate.yaml` 是最小兩 Stage 模式：

```text
Ralphy Task (Fresh Session, write)
        ↓
AI Validator (Fresh Session, read-only)
        ├─ PASS → 完成
        └─ FAIL → Fresh Ralphy Task → 再驗證
```

Workflow：

```yaml
stages:
  ralphy:
    type: task
    prompt: custom/common/ralphy.md
    fresh_session_on_start: true

  validate_ai:
    type: ai_validator
    validator: ai
    fresh_session_on_start: true
    runs: 1
    required_passes: 1
    recover: [ralphy]

flow:
  - ralphy
  - validate_ai
```

這個 Workflow 不使用 Plan、Review 或 bounded semantic recovery。`validate_ai` 只要回傳 semantic FAIL，就先重新進入 Fresh `ralphy` session 修正，再以 Fresh AI Validator session 重新驗證；**沒有 PASS 就不會正常完成 Workflow**。Technical/API error 仍由 Runner 既有 retry / fail-closed policy 處理。

`ralphy.md` 採單一任務、最小改動、必要測試、避免無關 refactor 的 coding-loop 風格；Recovery 時會直接讀取前一次 AI Validation 的 blocking evidence。
