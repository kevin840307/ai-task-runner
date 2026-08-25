# 使用指南

版本：1.2.33

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
未傳 `--workflow` 時，Runner 會依 validator 參數選擇內建檔：Python validator 加 AI validation instructions 使用 `mixed.yaml`，只有 Python validator 使用 `file.yaml`，`--validator ai` 使用 `ai.yaml`。YAML List 也會逐 item 獨立選擇。自訂檔案就是單一線性 YAML list，不需要 flow name、route 或外層 object：

```yaml
- stage: planning
  retry: 2
- stage: run_prompt
  id: generate_report
  prompt: prompts/generate.md
  retry: -1
- stage: review
  prompt: prompts/review.md
  retry: 1
  skip: true
- stage: validate_file
  retry: -1
- stage: validate_ai
  retry: -1
  runs: 3
  required_passes: 2
```

`planning` 仍會回傳產生出的 TODO `execute -> review` groups；`Pipeline` 會先遞迴跑完這些 group，再繼續下一個頂層 YAML Stage。未來任何 Stage 都可回傳相同的 `StageResult.next_flow` contract，Pipeline 沒有 Planning 專用分支。

目前頂層支援 `planning`、`run_prompt`、`review`、`validate_file`、`validate_ai`。`prompt` 是 UTF-8 instruction file，路徑以 Workflow YAML 所在目錄為基準；`run_prompt` 與頂層 `review` 必填，`validate_ai` 可用它追加驗證指示。同一 Stage type 出現多次時，請用唯一 `id` 區分。`retry: -1` 表示持續恢復直到取得有效 Stage result，`0` 表示不做 Same Session retry，非負正數則是有限次數。`review` 的 `skip: true` 只允許在技術性 recovery error 用盡後略過；有效的邏輯 FAIL 仍會進入 repair。`runs` 與 `required_passes` 可覆寫該 Final AI Stage 的 voting 設定。所有參數都可省略，未指定時沿用現有 Runner config；上方展開值是為了說明每個 override 應放的位置。

支援三種 validation topology：Mixed（`planning -> validate_file -> validate_ai`）、file-only（`planning -> validate_file`）、AI-only（`planning -> validate_ai`）。必須有唯一 `planning` 與至少一個 final validator；兩種 validator 都存在時，`validate_file` 必須先於 `validate_ai`，且實際 final validator 必須放在 list 最後。其他 Stage 可插在 final validation 前。

```yaml
# File-only
- planning
- stage: validate_file
  retry: -1
```

```yaml
# AI-only
- planning
- stage: validate_ai
  retry: -1
  runs: 3
  required_passes: 2
```

Runtime validation 也會確認拓樸符合 `--validator`：Python validator 不可省略 file validation；`--validator ai` 或 Mixed validation 不可省略 AI validation。Resume 會保存頂層位置與 Workflow fingerprint；自訂 Workflow resume 時必須再次傳入相同 `--workflow`。若 Workflow 已變更，Runner 會拒絕 resume，避免把舊游標套到新拓樸。

YAML List 遇到第一個 non-zero result 就停止後續 item；已完成 item 的 state 保留，可供 Debug/Resume 判斷。

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
from runner import RunRequest, run
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
