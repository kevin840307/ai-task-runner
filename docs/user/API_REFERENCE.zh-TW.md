# Python API 參考

版本：1.2.53

## 正式共用入口
外部 caller 應使用 `runner.api.RunRequest` 與 `runner.api.run()`。CLI、未來 UI、Skill 都應轉成同一個 request model，不應再做第二套 Runner flow。

`runner.api` 是唯一公開的 execution import path；過時的 package-level execution re-export 直接移除，不維護平行 compatibility API。

## RunRequest 欄位
`goal`、`goal_file`、`project_root`、`script`、`workflow_file`、`validator`、`validator_prompt`、`ai_validator_prompt`、`ai_validator_prompt_file`、`backend`、`command`、`sandbox`、`agent_args`、`validator_args`、`protect_files`、`validator_timeout`、`agent_timeout`、`planning_timeout`、`agent_idle_after_change_timeout`、`max_attempts`、`max_cycles`、`retry_delay`、`retry_wait`、`retry_max_wait`、`final_ai_validations`、`final_ai_required_passes`、`plugins`、`work_dir`、`resume`、`force_new`、`plan_only`、`human_output`、`json_events`。

`RunRequest.normalized_config()` 會解析 request file、映射公開欄位並回傳經驗證的 `RuntimeConfig`；`RunRequest.validate()` 委派給同一路徑。`RuntimeConfig.validate()` 統一負責 backend、work_dir 不可逃出 project root、timeout/retry 範圍、Final AI quorum，以及 resume/force-new 衝突等執行設定規則。CLI 只保留單向 `Namespace -> RunRequest` 邊界；內部執行不接受或重建舊 Namespace。

## 範例
```python
from runner.api import RunRequest, run

result = run(RunRequest(
    goal_file='prompt.md',
    project_root='project',
    workflow_file='workflow.yaml',
    validator='validation.py',
    ai_validator_prompt_file='ai_validation.md',
    final_ai_validations=3,
    validator_args=['--fab', 'FAB23'],
    backend='qwen',
))
print(result.exit_code, result.completed)
```

## Events
`run(request, on_event=callback)` 會把 progress/status/script event 傳給 callback。Callback 自己失敗是 fail-soft，不會中止 Runner。Transient service 等待視窗用盡或其他可恢復 Runner failure 時，會自動 resume 可用的 direct / YAML item state；deterministic `ConfigurationError` 與無效公開輸入仍會 fail-fast。`RunResult` 提供 `exit_code`、`state_files`、parsed `states` 與 `completed`。

## YAML script
`runner.script_loader` 負責解析非空 YAML array、結構欄位、alias 與引用檔案；`runner.script_runner` 使用 `dataclasses.replace()` 建立 child，並套用 API/CLI 共用的 `RuntimeConfig.validate()`。YAML 不另外維護 timeout、retry、quorum 或 Plugin option 規則。每筆必須在 `prompt`/`goal` 與 `goal_file` 中二選一，並提供 `validator` path 或 `ai`；相對 `goal_file`、`ai_validator_prompt_file`、`workflow_file` 都以 YAML 檔案所在目錄為基準。每筆可選 `validator_prompt`、`ai_validator_prompt`/`ai_validator_prompt_file` 二選一、Final AI quorum alias、`project_root`、`workflow_file` 與通用 `plugins` mapping。每筆相對 `project_root` 以外層 `--project-root` 為基準；未指定時維持原本共用 root 行為。舊 Plugin 欄位仍相容。每筆使用獨立 nested work dir；遇到第一個 non-zero 結果即停止整個 sequence。

`workflow_file` 只會 normalization 一次，成為 `RuntimeConfig.workflow`；格式與 User Guide 的線性 Workflow 相同。未指定時，direct request 與每個 YAML List item 都依自己的 validator 設定選擇 `workflow/builtin/mixed.yaml`、`workflow/builtin/file.yaml` 或 `workflow/builtin/ai.yaml`。明確指定的 parent Workflow 會由 YAML child 繼承；item 提供自己的 `workflow_file` 時，`dataclasses.replace()` 直接帶入已 normalization 的 child Workflow，不建立第二條執行路徑。

Retry 與 cycle 上限統一使用同一 sentinel：`-1` 表示持續恢復直到 PASS，`0` 表示停用該 retry/cycle，正數表示有限上限。預設 `max_attempts=2` 仍會在最多兩次 Same Session 恢復後切換 Fresh Session；預設 `max_cycles=-1` 讓無人職守驗證持續到 PASS。

Plugin 設定統一放在 `RunRequest.plugins` / `RuntimeConfig.plugins`。可設定的 Plugin 在自己的 module 內管理 CLI argument、YAML alias、預設值與驗證；新增 Plugin 不需要修改核心 config、YAML child 建立或 workflow。

## UI／可編輯資源／Stage Catalog
`runner.workflow.registry.stage_catalog()` 直接從每個已註冊 Stage 的 `spec_class` 輸出 metadata；UI/Tooling 不得另外維護 hardcode Stage schema。外部套件可使用 `ai_task_runner.extensions` entry-point group，在 Workflow validation 前註冊 Stage／Backend；只屬於 runtime 橫切能力的 Plugin 使用獨立 `ai_task_runner.plugins` group。

UI／Editor 直接使用真正 owner module：`runner.resources.read_text()` / `delete()`、`runner.workflow.loader.save_workflow()`、`runner.prompts.loader.save_prompt()`、`runner.workflow.registry.stage_catalog()`。刻意不再增加 `tooling` facade 或平行 API。Workflow save 使用真正 parser/schema，Prompt save 驗證 Jinja syntax；`expected_hash` 提供 optimistic conflict detection，atomic replace 避免半寫入檔案；若 caller 可能同時修改同一 Resource，必須自行 serialize 這些 mutation。這些 API 修改的就是未來 Run 真正使用的檔案，不建立 UI 專用第二套 Workflow。

Concrete Run 會在自己的 work directory 持久化 `workflow.snapshot.json`、Stage Prompt、`goal_file` 與 `ai_validator_prompt_file`；執行中或之後 Resume 即使來源檔已修改或刪除，也沿用同一份 frozen input，所以 UI/IDE 修改只影響新的 Run。`runner.api.state_files()` 不需重新載入 Workflow 就能定位 direct／YAML child state，可供 process supervisor 使用。

`type: python` 是唯一的通用 Python Stage；加上 `validator: file` 即啟用 deterministic validation 慣例；script 透過與 validator 共用的 process runner 在 subprocess 執行，任意 project Python 不會 import 進長時間 Runner process。
