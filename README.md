# AI Task Runner v1.1.1（Qwen / OpenCode）

AI Task Runner 是一個小型、可重用、可長時間執行的 AI CLI 控制器：

```text
理解專案 → 拆分 Tasks → 逐項實作 → 唯讀 Review
→ 最終 Python／AI Validator → FAIL 後重新規劃與修復 → PASS
```

AI 負責理解、實作與語意判斷；Python 負責狀態、格式、Retry、Timeout、檔案保護與最終完成判定。

## 最快開始

```bat
pip install -r requirements.txt
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --goal "完成指定功能並補齊測試" ^
  --validator C:\validators\validator.py
```

使用 AI Validator：

```bat
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --goal "完成指定功能並補齊測試" ^
  --validator ai
```

中斷或程序被 supervisor 重啟後，以相同專案與設定加上：

```bat
--resume
```

Resume 會從 state 讀取原本 Goal，因此不用再次提供 `--goal`。

## 24 小時模式

建議設定：

```bat
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --goal "完成需求並通過驗證" ^
  --validator C:\validators\validator.py ^
  --agent-timeout 7200 ^
  --validator-timeout 1200 ^
  --max-attempts 0 ^
  --max-cycles 0
```

行為：

- 模型非零結束、空輸出、破損 JSON、Schema 錯誤、Session 暫時失效與 Agent timeout 會自動退避 Retry。
- Task Review 未完成時，Task 維持 `pending` 並重新執行。
- Validator FAIL 時保留一般專案修改，將診斷結果交回主 Session 重新拆分修復工作。
- `max_attempts=0` 與 `max_cycles=0` 代表不限制邏輯重做與修復 Cycle。
- 單次 AI CLI 預設最多 7200 秒；超時會終止程序樹並 Retry。
- Python Validator timeout 也會終止程序樹，不只終止最外層 Python。

Runner 可保證：**只要 Runner process、主機、磁碟與外部 CLI 仍可運作，所有可恢復異常都不會讓工作流程誤判成功或直接放棄。**

Runner 無法保證：模型一定能解出不可行需求、主機永不斷電、磁碟永不耗盡，或 Python process 被 OS/OOM 終止後自行復活。正式 24h 使用應搭配 Windows Task Scheduler／NSSM 或 Linux systemd，並以 `--resume` 重啟。

完整說明：[使用手冊](docs/USER_GUIDE.md) · [架構設計](docs/DESIGN.md) · [異常測試矩陣](docs/TEST_MATRIX.md)

## 正式 Python API

```python
from runner_api import RunRequest, run

result = run(
    RunRequest(
        backend="qwen",
        command="qwen.cmd",
        project_root=r"C:\work\project",
        goal="完成需求",
        validator="ai",
        agent_timeout=7200,
    ),
    on_event=lambda event: print(event["type"]),
)

print(result.exit_code, result.completed)
```

JSON-like dictionary 也使用同一入口：

```python
result = run({
    "backend": "opencode",
    "project_root": "/work/project",
    "goal": "完成需求",
    "validator": "ai",
})
```

CLI、Python、UI 與 Skills 最終都呼叫 `runner_api.run()`，不存在第二套執行流程。

## 程式結構

```text
ai_task_runner.py       薄 CLI adapter
runner_api.py           RunRequest / RunResult / 唯一公開 run()
runner_core.py          TaskRunner、YAML、Validator 修復閉環
runner_support.py       Prompt、JSON、唯讀保護、UI、Retry
runner_models.py        Task / RunState
process_control.py      跨平台 timeout 與程序樹終止
agent.py                AgentClient Session facade
backends/
├── base.py             AgentBackend interface
├── qwen.py             Qwen command / decode
├── opencode.py         OpenCode command / decode
└── __init__.py         registry / factory
docs/
├── DESIGN.md
├── USER_GUIDE.md
└── TEST_MATRIX.md
```

`api.py`、`models.py`、`RunConfig`、`State`、`Agent`、`Backend` 只保留為舊版相容名稱。新程式應使用 `runner_api.RunRequest`、`RunState`、`AgentClient` 與 `AgentBackend`。

## Session 與完成判定

每個單一 Goal／YAML item 使用一個主 Session：

- 規劃
- Task 實作
- Task Review
- Validator FAIL 後重新規劃
- Resume

AI Validator 每次使用新的獨立 Session，不覆蓋主 Session ID。

完成判定：

```text
AI 說完成                 ≠ Task 完成
Task Review completed=true → Python 才更新 Task
所有 Tasks 完成           ≠ 整體完成
Final Validator PASS       → Python 才設定 completed=true
```

## Timeout

```text
--agent-timeout 7200      每一次 AI CLI 呼叫；0 表示不限制
--validator-timeout 600   Python Validator subprocess
```

`agent_timeout` 分別套用於規劃、Task 實作、Review、AI Validator 與重新規劃，不是整個 Task 累計時間。

Timeout 後：

```text
終止程序樹 → 保留一般專案修改 → 保護檔還原
→ 階段保持未完成 → 指數退避 → Retry 相同階段
```

## Retry 與限制

```text
--retry-wait 5
--retry-max-wait 300
```

預設退避：5、10、20、40 秒，最高 300 秒。

```text
--retry-delay 2       AI Review 明確判定未完成後，重做 Task 前等待
--max-attempts 0      單一 Task 最大邏輯 attempts；0 不限制
--max-cycles 0        Validator FAIL 修復 Cycle；0 不限制
```

command 不存在、project root／validator 路徑錯誤、YAML 格式錯誤等設定問題會 fail-fast，不進行無意義重試。v1.1.1 起，command 驗證失敗不會留下新的 state；`--force-new` 初始化失敗也不會破壞舊 state。

## Python Validator

Runner 執行：

```text
python validator.py --project-root <root> --state-file <state.json> [...validator args]
```

- Exit code `0`：PASS
- 其他：FAIL
- stdout／stderr 會保存並交給下一輪修復
- timeout、子程序樹與保護檔修改都會被處理

傳遞額外參數：

```bat
--validator-arg=--profile --validator-arg=test
```

## AI Validator

```bat
--validator ai ^
--validator-prompt "確認測試完整、沒有 hardcode，且 README 已更新"
```

AI Validator 為唯讀階段，必須回傳：

```json
{"passed": true, "reason": "checked", "missing_items": []}
```

若建立、修改、刪除或重新命名 tracked project files，Python 會還原並 Retry。

## YAML 批次

```yaml
- prompt: 修正登入流程並補齊測試
  validator: validators/login_validator.py

- prompt: 更新 README
  validator: ai
  validator_prompt: 確認文件與 CLI 參數一致
```

```bat
python ai_task_runner.py ^
  --backend qwen ^
  --command qwen.cmd ^
  --project-root C:\work\project ^
  --script tasks.yaml
```

各 item 依序執行、使用獨立主 Session 與獨立 state；前一項 PASS 才開始下一項。`--resume` 會跳過已完成項目並續跑未完成項目。

## UI／Skills

非 Python 整合使用：

```bat
python ai_task_runner.py ... --json-events
```

stdout 每行都是 JSONL，包含 `schema_version: 1` 與 `runner_version: 1.1.1`。Callback 或 JSON pipe 中斷不會停止 Runner。

UI／Skill 不應直接操作 `TaskRunner` 或修改 state，只需要：

```text
收集輸入 → 建立 RunRequest → 呼叫 run() → 顯示 events / RunResult
```

## 安全邊界

本工具不是 OS sandbox。Python 會保護 Runner、state、validator、Backend 規則與自訂 protect files；Review 與 AI Validator 會對 tracked project files 做唯讀還原。高風險環境仍應使用 OS 權限、容器或 VM。

預設排除可重建目錄：

```text
.git .ai-task-runner .idea .venv .vs __pycache__
bin build coverage dist node_modules obj target
```

## 測試狀態

v1.1.1 共 **87 項測試通過**，以隔離群組執行：

- 原有核心／API／Backend／Examples：55
- 新增異常與 24h 韌性測試：28
- 文件契約測試：4

Linux 已實際驗證 POSIX process group；Windows `taskkill /T /F` 路徑有單元測試，但仍建議在目標 Windows 主機做 Qwen／OpenCode 真實 12–24 小時 soak test。
