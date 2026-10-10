# 新增 Stage 並顯示在 Flow UI

若只是執行 Python 腳本或外部程式，使用現有的 `command` Stage 即可。需要獨立 Runner 行為時才新增 Stage 類型。Stage 只完成一次工作並回傳 `StageResult`；技術重試由共用 `StageExecutor` 負責，下一個 Stage 則由 Workflow 的結果連線決定。

## 可執行範例

[`examples/12_custom_stage_plugin`](../../examples/12_custom_stage_plugin/) 包含可安裝的 `echo` Stage、套件 entry point 和 Workflow YAML。從儲存庫根目錄，將兩個套件安裝到**啟動 UI 的同一個 Python 環境**：

```bash
python -m pip install -e .
python -m pip install -e examples/12_custom_stage_plugin --no-deps
```

範例的 `pyproject.toml` 宣告 `ai_task_runner.plugins` entry point。套件的 `setup()` 呼叫 `register_stage("echo", EchoStage)`。Stage class 提供 dataclass `spec_class`，其欄位會成為 UI 編輯參數；`name` 由 Workflow 積木提供，不列在參數編輯器中。

確認註冊與驗證：

```bash
python tool/workflow_catalog.py
python tool/workflow_dryrun.py examples/12_custom_stage_plugin/workflow.yaml --matrix --json
```

Catalog JSON 應出現 `stage_types.echo`，包含 `status`、`prefix` 選項；dry-run 應顯示 Workflow 已閉合。將範例 YAML 複製到 `runner/assets/workflows/` 可作為共用 Workflow，或複製到 `<project>/.ai-task-runner/assets/workflows/` 作為 Project Workflow。

啟動或重新啟動 `python ui/main.py`，再重新整理瀏覽器。UI server 透過 Runner subprocess 取得 `/api/workflow/catalog`，新的 `echo` 類型會自動出現在 Stage Palette 的**擴充積木**；`spec_class` 欄位會顯示在右側的**參數**頁籤。選擇 Project 並儲存 Workflow 後即可使用**測試**頁籤：輸入 `hello` 會得到 `Echo: hello`，下一個目標為 `done`，不會執行其他 Stage。

## 新增自己的類型

1. 定義包含 `name` 與可編輯選項的 dataclass spec。選填參數提供預設值；必填參數須在儲存 Workflow 前填妥。
2. 實作 `run(ctx, previous) -> StageResult` 和 `finish(ctx, result) -> StageResult`。不要在 Stage 內實作路由或重試。
3. 在 plugin `setup()` 內以 `register_stage("your_type", YourStage)` 註冊一次。
4. 在套件中宣告 `ai_task_runner.plugins` entry point，並安裝於 UI／Runner 使用的 Python 環境。
5. 在 Workflow YAML 使用 `type: your_type`。重新啟動 UI process 並重整頁面，讓 catalog 重新讀取。

Palette 依用途分類內建類型；沒有內建呈現資訊的新類型會以通用名稱顯示在**擴充積木**。編輯欄位與驗證仍由 Stage spec 提供，新增類型不必修改 Flow UI 程式碼。

Flow UI 的修改先保留在瀏覽器草稿，按**儲存 Workflow**後才會檢查檔案 hash、Stage／連線 schema、Prompt 引用與 Workflow dry-run；全部通過才原子寫入 YAML。未儲存時重新載入或離開會捨棄草稿。

## 先判斷是否真的需要新 Stage type

如果只是一般 AI 行為，優先使用既有 `type: base`：

- `profile: generic`：自訂 AI Prompt / instructions。
- `profile: execute`：可寫入的執行 Stage。
- `profile: review`：read-only 結構化 Review。

只有需要新的 runtime 行為時才新增特殊 Stage，例如 Plan、AI Validator、Command、Handoff 或 plugin Stage。這可以避免每個 Prompt/角色都長出一個新的 Python Stage class。

## Producer-defined dynamic child Workflow

特殊 Stage 可透過 `StageResult.kind = "tasks"` 或 `"stages"` 產生 child Workflow。

Runner 不產生 child Stage template。Producer Stage 自己負責回傳 child `stages`；Runner 只負責驗證、namespace、持久化、執行與 Resume。

`tasks` producer 的結果需包含：

- 非空 `tasks`。
- 非空 `stages`。
- 每個 Task 至少被一個 child 的 `task_id` 綁定。
- 每個 Task 至少有一個 child 設 `task_complete: true`。

child routes/hand-off targets 必須留在 child Workflow 內；若要結束 child 並回 parent，使用正常的 `next` / `done` / `stop` 語意。不要直接 route 到 parent 任意 Stage。

PlanStage 是目前第一個正式 producer：它解析 Tasks 後自行建立多組 `AI Stage(profile=execute) -> AI Stage(profile=review)`，全部完成後才回 parent 下一個 Stage。

所有 child Stage 都使用相同的 `runner/workflow/execution/stage_executor.py`，所以自訂 Stage 不需要實作 retry/recover/session logic。

