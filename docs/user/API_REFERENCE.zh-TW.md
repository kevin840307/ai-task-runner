# Python API 參考

版本：1.2.18

## 正式共用入口
外部 caller 應使用 `runner.api.RunRequest` 與 `runner.api.run()`。CLI、未來 UI、Skill 都應轉成同一個 request model，不應再做第二套 Runner flow。

舊版 compatibility 名稱可能仍為既有 caller 保留，但不屬於 canonical API，新 integration 不應使用。純 internal、已無 production caller 的 compatibility shim 會直接移除。

## RunRequest 欄位
`goal`、`goal_file`、`project_root`、`script`、`validator`、`validator_prompt`、`ai_validator_prompt`、`ai_validator_prompt_file`、`backend`、`command`、`sandbox`、`agent_args`、`validator_args`、`protect_files`、`validator_timeout`、`agent_timeout`、`planning_timeout`、`agent_idle_after_change_timeout`、`max_attempts`、`max_cycles`、`retry_delay`、`retry_wait`、`retry_max_wait`、`final_ai_validations`、`final_ai_required_passes`、`work_dir`、`resume`、`force_new`、`plan_only`、`human_output`、`json_events`。

`RunRequest.validate()` 會檢查 goal/script/validator 互斥與必填、backend、work_dir 不可逃出 project root、list element 型別、timeout/retry 範圍、Final AI quorum，以及 resume/force-new 衝突。

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
`run(request, on_event=callback)` 會把 progress/status/script event 傳給 callback。Callback 自己失敗是 fail-soft，不會中止 Runner。`RunResult` 提供 `exit_code`、`state_files`、parsed `states` 與 `completed`。

## YAML script
`runner.script_runner` 接受非空 YAML array。每筆必須在 `prompt`/`goal` 與 `goal_file` 中二選一，並提供 `validator` path 或 `ai`；相對 `goal_file` 與 `ai_validator_prompt_file` 都以 YAML 檔案所在目錄為基準。每筆可選 `validator_prompt`、`ai_validator_prompt`/`ai_validator_prompt_file` 二選一、`ai_validator_count`、`ai_validator_required_passes`、`project_root`。每筆相對 `project_root` 以外層 `--project-root` 為基準；未指定時維持原本共用 root 行為。舊格式仍相容。每筆使用獨立 nested work dir；遇到第一個 non-zero 結果即停止整個 sequence。

`max_attempts` 與 `max_cycles` 保留既有 API 欄位，但語意是恢復策略升級門檻，不是終止上限。可恢復的 workflow 錯誤會持續在 retry / fresh-session / replan 間循環，直到 Final Validator PASS。
