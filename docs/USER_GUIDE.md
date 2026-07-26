# AI Task Runner v1.1.1 使用手冊

## 1. 環境需求

- Python 3.10 以上
- Qwen CLI 或 OpenCode CLI 已安裝，且能在終端獨立執行
- `pip install -r requirements.txt`
- Target project 與 state 目錄可讀寫

先驗證 CLI：

```bat
qwen.cmd --help
opencode.exe --help
```

## 2. 基本執行

### Qwen

```bat
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --goal "完成指定功能並補齊測試" ^
  --validator ai
```

### OpenCode

```bat
python ai_task_runner.py ^
  --backend opencode ^
  --command opencode.exe ^
  --project-root C:\work\project ^
  --goal "完成指定功能並補齊測試" ^
  --validator ai
```

模型參數：

```bat
--agent-arg=--model --agent-arg=provider/model
```

含空白的 executable path：

```bat
--command "C:\Program Files\Qwen\qwen.cmd"
```

## 3. Validator

### Python Validator

```bat
--validator C:\validators\validator.py
```

Runner 追加：

```text
--project-root <project-root>
--state-file <state.json>
```

Validator 應將具體診斷寫到 stdout／stderr：

```text
FAILED: test_login_invalid_token
Expected: HTTP 401
Actual: HTTP 500
Related file: src/auth/login.py
```

Exit code 0 代表 PASS，其他代表 FAIL。

### AI Validator

```bat
--validator ai ^
--validator-prompt "確認既有 API 相容、測試完整且文件已更新"
```

AI Validator 使用新的獨立 Session，且由 Python 強制唯讀。

## 4. Resume 與 Force New

Resume：

```bat
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --validator ai ^
  --resume
```

Resume 不需要再次提供 `--goal`，Goal 會從 state 載入。

State 路徑：

```text
單一 Goal：.ai-task-runner/state.json
YAML：.ai-task-runner/script/001/state.json
```

需要捨棄現有進度並建立新 run：

```bat
--force-new
```

`--resume` 與 `--force-new` 不可同時使用。

v1.1.1 會檢查：

- State 是否存在
- JSON 是否完整
- Task status／current／cycle 是否有效
- State 是否屬於目前 project root

初始化 command 失敗時不會留下半成品 state；Force New 初始化失敗也會保留原 state。

## 5. 24 小時執行

推薦：

```bat
--agent-timeout 7200 ^
--planning-timeout 120 ^
--validator-timeout 1200 ^
--retry-wait 5 ^
--retry-max-wait 300 ^
--max-attempts 0 ^
--max-cycles 0
```

### 自動恢復表

| 情境 | 行為 |
|---|---|
| CLI 非零 exit | Backoff 後 Retry |
| 空輸出／破損 JSON | 同階段 Retry |
| Task／Review／AI Validator Schema 錯誤 | 同階段 Retry |
| Execution／Review／AI Validator 連續模型錯誤 | 保存診斷，回到 Task／Validator 流程換策略 |
| Session not found／expired／invalid | 清除 Session，建立新 Session 承接 State |
| Task Review `completed=false` | Task 保持 pending，重做 |
| 連續三次無進度 | Prompt 要求改變策略 |
| Planning timeout | 重新建立簡單可執行 Task，避免卡在規劃 |
| Agent timeout | 終止程序樹，保留一般修改，Retry |
| Python Validator timeout | 終止程序樹，保留輸出，FAIL 後修復 |
| Validator FAIL | 保留修改、cycle+1、重新規劃 |
| Validator 連續同錯誤 | 進入 repair mode，要求先跑 validator 並修第一個失敗點 |
| UI callback／JSON pipe 中斷 | Runner 繼續 |
| Python／主機重啟 | 外部 supervisor 以 `--resume` 重啟 |

### Supervisor

Windows Task Scheduler／NSSM 或 Linux systemd 應以固定命令重啟：

```text
python ai_task_runner.py ... --resume
```

首次執行與 Resume 命令可分成兩個 wrapper；supervisor 的 restart 命令使用 Resume。

### State 監控

`state.json` 會保存 `stage`、`stage_started_at`、`last_activity_at`、`last_error`、`validator_failure_count`。24 小時執行時可用這些欄位判斷目前是在 planning、execution、review、validation、等待 retry，或已進入 validator repair mode。

### 保證邊界

Runner 不會在 Validator 未 PASS 時把整體標成完成，也不會因可恢復的模型錯誤主動放棄。但以下仍可能停止或永遠無法完成：

- OS／OOM 終止 Python
- 主機斷電且沒有 supervisor
- 磁碟耗盡、權限失效
- 外部服務或憑證永久不可用
- Goal 或 Validator 條件互相衝突
- 模型能力不足，始終無法收斂
- CLI 建立完全脫離原程序樹的 daemon

## 6. Timeout 語意

### Planning

```text
--planning-timeout 120
```

每一次 Planning／Re-plan 獨立計時。`0` 表示不限制。

Qwen 這類小模型如果在規劃階段 timeout 或觸發循環偵測，Runner 會改用需求本身建立 fallback task，讓實作階段繼續交給 Agent 完成；若需求本身列出 `1.`、`2.`、`3.` 這類編號 deliverables，Runner 會保留為多個有序 task。Runner 不會寫入任務專用程式碼。

### Agent

```text
--agent-timeout 7200
```

每一次模型 CLI 呼叫獨立計時：

- Task execution
- Task Review
- AI Validator

`0` 表示不限制。它不是整個 Task 的累計上限。

本地小模型 smoke test 可先用 360～600 秒；正式 24 小時無人值守建議用 7200 秒或依專案大小提高。Planning 維持 120 秒即可，避免小模型卡在拆任務階段。

### Python Validator

```text
--validator-timeout 600
```

必須為正整數。Timeout 後會保留 partial output，並終止 validator 與正常子程序樹。

## 7. Retry 與停止條件

```text
--retry-wait 5
--retry-max-wait 300
```

模型呼叫異常使用指數退避。

```text
--retry-delay 2
```

只用於 Review 明確判定 Task 未完成後的邏輯重做。

```text
--max-attempts 0
--max-cycles 0
```

- `0`：不限制
- 正數：達限後分別以 exit code 2／3 停止

## 8. YAML 批次

```yaml
- prompt: 修正登入功能
  validator: validators/login.py

- prompt: 更新文件
  validator: ai
  validator_prompt: 確認文件與實作一致
```

```bat
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --script tasks.yaml
```

YAML 必須是非空 array；每個 item 必須有 `prompt`／`goal` 與 `validator`。

## 9. Python API

```python
from runner_api import RunRequest, RunResult, run

request = RunRequest(
    goal="完成需求",
    project_root=r"C:\work\project",
    validator="ai",
    backend="qwen",
    command="qwen.cmd",
    agent_timeout=7200,
)

result: RunResult = run(request, on_event=print)
```

`run()` 為同步函式。GUI 應在 worker thread 或獨立 subprocess 執行。

## 10. JSON Events

```bat
python ai_task_runner.py ... --json-events
```

事件類型：

```text
runner.progress
runner.status
runner.error
runner.stopped
script.item_started
script.item_completed
script.item_failed
```

每行是獨立 JSON，包含 `schema_version=1` 與 `runner_version=1.1.1`。

## 11. CLI 參數

| 參數 | 預設 | 說明 |
|---|---:|---|
| `--goal` | 無 | 單一需求；Resume 可省略 |
| `--project-root` | `.` | Target project |
| `--script` | 無 | YAML 批次 |
| `--validator` | 必填 | Python path 或 `ai` |
| `--validator-prompt` | 空 | AI Validator 額外規則 |
| `--backend` | `qwen` | `qwen`／`opencode` |
| `--command` | Backend 預設 | CLI executable |
| `--agent-arg` | 無 | 可重複 |
| `--validator-arg` | 無 | 可重複 |
| `--protect-file` | 無 | 額外保護檔；相對路徑以啟動 cwd 解讀 |
| `--agent-timeout` | `7200` | 單次 AI CLI；0 不限制 |
| `--planning-timeout` | `120` | Planning／Re-plan AI CLI；0 不限制 |
| `--validator-timeout` | `600` | Python Validator |
| `--max-attempts` | `0` | Task attempts；0 不限制 |
| `--max-cycles` | `0` | Validator cycles；0 不限制 |
| `--retry-delay` | `2` | Task 未完成重做等待 |
| `--retry-wait` | `5` | Model retry 初始等待 |
| `--retry-max-wait` | `300` | Model retry 最大等待 |
| `--work-dir` | `.ai-task-runner` | 必須在 project root 內 |
| `--json-events` | false | JSONL event stream |
| `--resume` | false | 從 state 繼續 |
| `--force-new` | false | 建立新 run |

## 12. Troubleshooting

### `command not found`

先在相同帳號與環境執行 CLI；必要時用完整路徑。此錯誤 fail-fast，不會建立新 state。

### `state exists`

使用 `--resume` 繼續，或明確使用 `--force-new`。

### `invalid resume state`

State JSON、current、cycle、status 或 project root 不合法。不要手動修改 state；從備份恢復或 Force New。

### Session 一直失效

確認 CLI 版本與 resume/session 參數是否仍相容。Runner 只對明確 Session invalid 訊息重建 Session。

### Validator 一直 FAIL

改善 validator 診斷，列出 expected／actual／test／file。確認 Validator 條件確實可達成。

### Timeout 太頻繁

一般專案使用 3600～7200 秒；本地大型模型或大型 repository 可提高到 14400 秒。Task 若預估超過 60～90 分鐘，優先拆小而不是無限提高 timeout。
