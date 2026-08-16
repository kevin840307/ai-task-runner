# 使用指南

版本：1.2.0

## 單一 Goal
`python ai_task_runner.py --goal-file prompt.md --project-root <project> --validator validation.py`

也可用 `--goal "..."` 直接給文字；`--goal` 與 `--goal-file` 互斥。

## Validator 額外參數
每一個 argv element 都重複一次 `--validator-arg`：
`--validator-arg "--fab" --validator-arg "FAB23" --validator-arg "--env" --validator-arg "PROD"`。
不要寫 `--validator "validation.py --fab FAB23"`；`--validator` 只接受 validator path 或 literal `ai`。

## Project policy
`.ai-task-runner.yaml` 必須直接放在 `project-root`：
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
Protected path 是 project-relative，可指檔案或資料夾；資料夾會保護整個 subtree。Policy 本身會自動 protected，不需再次列進 `protected_paths`。Runner 不會往 parent directory 找 policy。

## Resume / Restart
- `--resume`：延續相容 state。
- `--force-new`：忽略舊 run state，重新開始。
- 兩者不能同時使用。
- `--plan-only`：只建立/更新 TODO 並保存 state，不執行 TODO。

## YAML script mode
`--script tasks.yaml` 依序執行 YAML array。每筆必須有 `prompt`（或 `goal`）與 `validator`；可選 `validator_prompt`、`ai_validator_prompt`、`ai_validator_count`、`ai_validator_required_passes`。每個 script item 使用 `.ai-task-runner/script/<index>` 隔離 state。

```yaml
- prompt: 完成這次需求修改。
  validator: validation.py
  ai_validator_prompt: >-
    檢查架構、通用性與不必要的複雜度。
  ai_validator_count: 3
```

## Validation 模式
- File validator：`--validator validation.py`。
- AI validator：`--validator ai`，可加 `--validator-prompt`。
- 混合驗證：使用 file `--validator` 再加 `--ai-validator-prompt`。Python validator 是硬性 gate，只有 PASS 才執行 AI 投票，而且兩邊都必須 PASS。
- `--final-ai-validations`（alias：`--ai-validator-count`）控制 fresh session 的獨立票數；`--final-ai-required-passes 0` 代表嚴格過半，也可指定固定門檻。

範例：`--validator validation.py --ai-validator-prompt "檢查架構與通用性" --ai-validator-count 3` 代表 Python 必須 PASS，且 3 個獨立 AI session 至少 2 票 PASS。

## JSON events / Integration
`--json-events` 輸出 JSON Lines。Python/UI/Skill 應使用 `runner.api.RunRequest` + `runner.api.run()`，這是正式共用入口。

## Backend 參數
每個 backend argv item 都重複 `--agent-arg`。`--command` 只用於覆寫 backend executable。Qwen 完整 Prompt 固定 stdin-only。

## CLI Protected path
額外保護可重複使用 `--protect-file`；長期專案規則建議放 project-root policy。

## Debug
異常時查看 `<project-root>/.ai-task-runner/debug/current-prompt.txt`、`last-prompt.txt`、`last-result.txt` 與 `debug/history/`。
