# Python API 參考

版本：1.2.33

## 正式共用入口
外部 caller 應使用 `runner.api.RunRequest` 與 `runner.api.run()`。CLI、未來 UI、Skill 都應轉成同一個 request model，不應再做第二套 Runner flow。

舊版 compatibility 名稱可能仍為既有 caller 保留，但不屬於 canonical API，新 integration 不應使用。純 internal、已無 production caller 的 compatibility shim 會直接移除。

## RunRequest 欄位
`goal`、`goal_file`、`project_root`、`script`、`validator`、`validator_prompt`、`ai_validator_prompt`、`ai_validator_prompt_file`、`backend`、`command`、`sandbox`、`agent_args`、`validator_args`、`protect_files`、`validator_timeout`、`agent_timeout`、`planning_timeout`、`agent_idle_after_change_timeout`、`max_attempts`、`max_cycles`、`retry_delay`、`retry_wait`、`retry_max_wait`、`final_ai_validations`、`final_ai_required_passes`、`plugins`、`work_dir`、`resume`、`force_new`、`plan_only`、`human_output`、`json_events`。

`RunRequest.normalized_config()` 會解析 request file、映射公開欄位並回傳經驗證的 `RuntimeConfig`；`RunRequest.validate()` 委派給同一路徑。`RuntimeConfig.validate()` 統一負責 backend、work_dir 不可逃出 project root、timeout/retry 範圍、Final AI quorum，以及 resume/force-new 衝突等執行設定規則。CLI 只保留單向 `Namespace -> RunRequest` 邊界；內部執行不接受或重建舊 Namespace。

## 範例
```python
from runner.api import RunRequest, run

result = run(RunRequest(
    goal_file='prompt.md',
    project_root='project',
    validator='validation.py',
    ai_validator_prompt_file='ai_validation.md',
    final_ai_validations=3,
    validator_args=['--fab', 'FAB23'],
    backend='qwen',
))
print(result.exit_code, result.completed)
```

## Events
`run(request, on_event=callback)` 會把 progress/status/script event 傳給 callback。Callback 自己失敗是 fail-soft，不會中止 Runner。Transient service 等待視窗用盡後會自動 resume 可用的 direct 或 YAML item state；non-transient 與 deterministic configuration error 仍會交還 caller。`RunResult` 提供 `exit_code`、`state_files`、parsed `states` 與 `completed`。

## YAML script
`runner.script_loader` 負責解析非空 YAML array、結構欄位、alias 與引用檔案；`runner.script_runner` 使用 `dataclasses.replace()` 建立 child，並套用 API/CLI 共用的 `RuntimeConfig.validate()`。YAML 不另外維護 timeout、retry、quorum 或 Plugin option 規則。每筆必須在 `prompt`/`goal` 與 `goal_file` 中二選一，並提供 `validator` path 或 `ai`；相對 `goal_file` 與 `ai_validator_prompt_file` 都以 YAML 檔案所在目錄為基準。每筆可選 `validator_prompt`、`ai_validator_prompt`/`ai_validator_prompt_file` 二選一、Final AI quorum alias、`project_root` 與通用 `plugins` mapping。每筆相對 `project_root` 以外層 `--project-root` 為基準；未指定時維持原本共用 root 行為。舊 Plugin 欄位仍相容。每筆使用獨立 nested work dir；遇到第一個 non-zero 結果即停止整個 sequence。

Retry 與 cycle 上限統一使用同一 sentinel：`-1` 表示持續恢復直到 PASS，`0` 表示停用該 retry/cycle，正數表示有限上限。預設 `max_attempts=2` 仍會在最多兩次 Same Session 恢復後切換 Fresh Session；預設 `max_cycles=-1` 讓無人職守驗證持續到 PASS。

Plugin 設定統一放在 `RunRequest.plugins` / `RuntimeConfig.plugins`。可設定的 Plugin 在自己的 module 內管理 CLI argument、YAML alias、預設值與驗證；新增 Plugin 不需要修改核心 config、YAML child 建立或 workflow。
