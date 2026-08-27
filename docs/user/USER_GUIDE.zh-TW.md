# 使用指南

版本：1.2.40

## 單一 Goal
`python ai_task_runner.py --goal-file prompt.md --project-root <project> --validator validation.py`

若是短文字可使用 `--goal "..."`。`--goal` 與 `--goal-file` 互斥，只能選一種。

## Validator 額外參數
每一個 argv element 都要各自重複一次 `--validator-arg`：
`--validator-arg "--fab" --validator-arg "FAB23" --validator-arg "--env" --validator-arg "PROD"`。

不要寫成 `--validator "validation.py --fab FAB23"`；`--validator` 只接受 Validator path 或 literal `ai`。Runner 不解析 FAB/ENV 等 business semantics，只把參數原樣傳給 Validator。

## Project policy
在 `project-root` 直接放置 `.ai-task-runner.yaml`：
```yaml
protected_paths:
  - input/
  - ans/
instructions:
  always: |
    Keep changes minimal.
    Never hardcode project-specific values.
  project: |
    Reuse existing architecture and helpers.
```

Protected path 以 project root 為基準，可指定檔案或資料夾。Policy 檔本身會自動受到保護，不必再放進 `protected_paths`。Runner 不會往父資料夾尋找 policy，因此每個獨立 project root 都應維護自己的 policy。

## Resume / Restart
- `--resume`：延續相容的 durable Runner state。
- `--force-new`：忽略舊 run state，建立新的 run。
- `--resume` 與 `--force-new` 不能同時使用。
- `--plan-only`：建立或更新 TODO、保存 state，然後在 Execute 前退出。

Resume 時若 state 已保存原始 Goal，就不需要再次提供 `--goal`；重複提供相同 Goal 也可以。

## YAML script mode
`--script tasks.yaml` 會依序執行 YAML array。每筆必須在 `prompt`/`goal` 與 `goal_file` 中二選一，並提供 `validator`。`goal_file` 與 `ai_validator_prompt_file` 使用 UTF-8；相對路徑都以 YAML 檔案所在目錄為基準。

可選欄位包含 `validator_prompt`、`ai_validator_prompt`/`ai_validator_prompt_file` 二選一、`ai_validator_count`、`ai_validator_required_passes`、`project_root`、`workflow_file`。每筆引用的相對檔案路徑（包含 `workflow_file`）都以 script YAML 所在目錄為基準。每筆相對 `project_root` 以外層 `--project-root` 為基準；未指定時維持共用 root。每個 item 都在自己的 `<project-root>/.ai-task-runner/script/<index>` 保存 Runner-managed state；外層 YAML orchestrator 只送出 callback／JSON／UI event，不會再建立另一個 work directory。完成判定與 resume 使用各 item 的 state path。內層 runtime 結束後會恢復外層 script runtime，避免 Plugin/Event/State context 互相污染。

```yaml
- goal_file: prompts/example-a.md
  project_root: projects/example-a
  validator: validation.py
  ai_validator_prompt_file: ai_validation.md
  ai_validator_count: 3
  workflow_file: workflows/build.yaml
```

## Workflow YAML
未傳 `--workflow` 時，Runner 會依 validator 設定選擇 `workflow/builtin/mixed.yaml`、`workflow/builtin/file.yaml` 或 `workflow/builtin/ai.yaml`。Workflow YAML 只保留兩個頂層 key：`stages` 定義可重用 node，`flow` 定義執行順序；單次 flow item 可以覆寫 Stage instance。一般 AI-backed node 使用 `BaseStage`，`type` 預設為 `base`，通常省略。

Planning 是刻意保留的特殊動態 Stage。YAML 不需要 `expand`、`foreach` 或額外 subflow DSL；不在頂層 static flow、不是 recovery-only、不是 planner/validator 的 Stage 定義會自動成為 Planner 可選能力。`PlanStage` 會為每個 TODO 選擇 ordered Stage sequence，並以 `next_steps` 回傳。

```yaml
stages:
  planning:
    type: plan
    status: Plan
    result_handler: plan

  execute:
    status: Execute
    mode: write
    prompt: stages/execution.md
    result_handler: task

  security_review:
    status: Security review
    prompt: prompts/security_review.md

  review_task:
    status: Review
    prompt: stages/review.md
    parser: review
    result_status: completed
    result_handler: review

  validate_file:
    type: python
    validator: file
    status: Validate
    result_handler: validation

flow:
  - planning
  - validate_file
```

在這份 YAML 中，Planner 可以選 `execute`、`security_review`、`review_task`，但不能選 `planning` 或 `validate_file`。某個 TODO 因此可以產生 `steps: [execute, security_review, review_task]`。Stage 名稱會在執行前完成驗證，並和 TODO 一起寫入 durable state，再轉成 `StageResult.next_steps` 交給 Pipeline 執行。若存在 review-capable Stage，每個 TODO 的最後一步必須是 review Stage。Planning 完成後即使在 queue 寫入前 crash，Resume 也能從已保存的 TODO steps 重建，不需要重新問模型規劃。

同一個可重用 `BaseStage` 可以在 flow 中重複使用，且每次給不同 prompt：

```yaml
stages:
  run_prompt:
    status: Run prompt
    mode: write

  review:
    status: Review
    mode: readonly
    parser: review
    result_status: completed

  validate_file:
    type: python
    validator: file
    status: Validate
    result_handler: validation

flow:
  - stage: run_prompt
    prompt: prompts/step_a.md

  - stage: review
    prompt: prompts/review_a.md
    retry: 1
    skip: true

  - stage: run_prompt
    prompt: prompts/step_b.md

  - stage: review
    prompt: prompts/review_b.md
    skip: false

  - stage: run_prompt
    prompt: prompts/step_c.md

  - validate_file
```

`skip` 是 `skip_on_error` 的精簡 alias。`type: plan` 表示 Planning、`type: python` 表示 Python Validator；`type: base` 可以明寫，但一般可省略。`validator: file|ai` 表示 validation capability。`recover` 直接放靜態 recovery Stage sequence，`restart_at` 仍是 FlowNode routing metadata。動態規劃只來自已驗證的 `PlanStage.next_steps`；YAML 不再有 `expand`/`foreach`。`instructions_file` 以 Workflow YAML 所在目錄為基準載入 UTF-8 instructions；相對 `prompt` path 若在 Workflow YAML 旁存在，會優先解析為該本地檔案，否則保留 bundled prompt path，例如 `stages/execution.md`；`retry` 可為 `-1`、`0` 或有限非負整數。Final validation 必須放最後；同時有兩種 validator 時，file validation 必須先於 AI validation。

## Validation 模式
- Python/File Validator：`--validator path/to/validation.py`。
- AI-only Validator：`--validator ai`，可搭配 `--validator-prompt`。
- Mixed Validation：使用 file `--validator`，再加 `--ai-validator-prompt` 或 `--ai-validator-prompt-file`。Python Validator 是 deterministic hard gate，必須先 PASS；之後 Final AI voting 才會執行，而且兩個 gate 都要 PASS。
- `--final-ai-validations`（alias `--ai-validator-count`）控制獨立的 Fresh Session 驗證次數。
- `--final-ai-required-passes 0` 使用嚴格過半；設為正整數時，必須達到明確指定的 PASS 數。

例如 `--validator validation.py --ai-validator-prompt-file ai_validation.md --ai-validator-count 3` 代表 Python Validator 必須 PASS，接著 3 個不同 Fresh Session 獨立驗證；未指定 required passes 時至少 2/3 PASS。

若設定 `--ai-validator-required-passes 3`，則必須 3/3 PASS。

## Session Recovery
- Same Session 是正常 failure 的第一 recovery 路徑，只補 Stage 身分、新 failure evidence 與下一步，不重送完整 Context。
- Same Session retry budget（預設 2）用盡後，才建立 Fresh Session，並提供完整且必要的 Context。
- Fresh Session 仍出現相同 persistent failure 時才升級 Replan；failure fingerprint 改變則重新計數。
- Final AI Validation 與一般 recovery 不同：每個 configured vote 都必須使用不同 Fresh Session。後續 vote 遇到模型異常並恢復時，已完成的 vote 會保留；若 safety hook 拒絕該 attempt，該次新增的 vote 會丟棄。
- Structured Output correction 最多先做 2 次 Same Session retry，仍失敗才依設定 Fresh fallback。

## JSON events / Integration
`--json-events` 輸出 JSON Lines。Python caller 應使用 `runner.api.RunRequest` 與 `runner.api.run()`；未來 UI/Skill 也應適配同一個 API，不建立第二套 orchestration。

Workflow 不直接依賴 raw event schema 或具體 Plugin；Workflow 只透過 semantic progress facade 回報狀態，raw event type/schema 由 runtime 層管理。

## Backend 參數
每一個 backend argv item 都各自重複 `--agent-arg`。`--command` 只用於覆寫 backend executable。`--sandbox` 會在 backend 支援時啟用 sandbox；Qwen 會收到 `-s`。

所有完整 AI task Prompt 都固定透過 stdin 傳入，避免 Windows command-line 長度限制。Qwen 的 `/context`、`/compress-fast` 是短的 backend control command，不是 task Prompt，因此可使用 CLI control argument。

## CLI Protected path
可重複使用 `--protect-file` 加入額外 protected path。長期穩定的 project-owned rule 優先放在 `.ai-task-runner.yaml`。

Readonly Stage 如果嘗試修改檔案，Safety Plugin 會還原修改並把該 attempt 視為 failure；Same Session retry 只補 Stage 身分、新 failure evidence 與下一步，不重送完整 Context。

## Debug
診斷 AI 行為時可查看：
- `<project-root>/.ai-task-runner/debug/current-prompt.txt`
- `last-prompt.txt`
- `last-result.txt`
- `debug/history/`

Log/Event 應維持精簡，但要保留 Session mode、Stage、retry/recovery、process exit、validator result 等足以定位 24H 問題的資訊。`log.txt` 與 `exception.log` 到 10 MB 時 rotate，並保留一份上一代；model-call history 使用自己獨立的 bounded policy。

## Timeout 預設值
| Option | Default |
|---|---:|
| `--agent-timeout` | `7200` |
| `--planning-timeout` | `600` |
| `--agent-idle-after-change-timeout` | `900` |
| `--validator-timeout` | `1200` |

Transient API/network/rate-limit/service error 使用獨立 backoff window，不消耗 Stage failure budget；真實 Stage failure 才走 Same Session -> Fresh Session -> Replan。

## Canonical Python API
```python
from runner.api import RunRequest, run
```

CLI、Python API、YAML List 最終都走同一套 Runner orchestration；不要建立平行流程。

## External command validator
若真正的 Validator 是 exe、bat、jar 或其他 CLI，使用 `docs/validator_templates/external_command_validator.py` 作為 Python wrapper。外部 command 與 log folder 透過重複的 `--validator-arg` 傳入。Wrapper 會保存 stdout/stderr，並把符合設定的 log folder 複製到 `.ai-task-runner/validator-reports/external-command/`。

Deterministic Validator 應驗證 observable requirement，不應把 Planner 的拆解方式、class 數量或未在 Goal 明確要求的 coding style 當成 hard fail。

## Agent rule files
- Qwen Code：`QWEN.md`
- OpenCode：`AGENTS.md`

OpenCode 官方 project rule filename 是 `AGENTS.md`，不是 `AGENT.md`。

Runner-managed instruction section 由 `runner/project/instructions.py` 維護；project 自己的既有內容要被保留，不應由 Backend 任意覆寫。

## UI-ready 編輯與 Python Stage
未來 UI／CLI integration 共用 `runner.api.run()`，不直接呼叫 Pipeline 或 StageExecutor。`stage_catalog()` 直接從真正的 `spec_class` 提供已安裝 Stage type；外部 Stage／Backend 使用 `ai_task_runner.extensions` 註冊，runtime 橫切 Plugin 則使用 `ai_task_runner.plugins`。

Workflow／Prompt editor 應使用 `save_workflow()`／`save_prompt()`，並搭配 `runner.resources.read_text()` 回傳的 `expected_hash`。存檔會先驗證，再 atomic replace 真正來源檔。執行中的任務使用自己 work directory 內的 Workflow／Stage Prompt／Goal File／Final-AI Prompt snapshot，因此來源修改或刪除只影響下一個 Run，不影響 active／resumed Run。

使用者 Python 步驟使用 `type: python_script`，設定 `path` 與可選 `args`；它在 subprocess 執行，仍走一般 StageExecutor Hook/change/recovery boundary，不把 project Python import 進長時間 Runner process。


## OpenCode runtime contract

OpenCode 完整 AI task Prompt 與 Qwen 一樣走 stdin，不放在 argv。Resume 使用官方 `--session`；non-interactive call 自動加入 `--auto`。Planning/no-tool/review 的工具權限由 Backend adapter 透過 `OPENCODE_CONFIG_CONTENT` 的 `permission` runtime override 控制。`--sandbox` 會額外 deny `external_directory`。OpenCode 官方目前沒有 Qwen `-s` 的 container sandbox 等價旗標，因此這是 permission-based confinement；Runner 的 protected-path、Git guard、readonly restore 仍是共同的硬保護。
