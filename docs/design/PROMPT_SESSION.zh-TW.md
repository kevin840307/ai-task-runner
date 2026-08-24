# Prompt 與 Session 契約

## Prompt Variables

Prompt 變數是正式 contract，不是各 Stage 自行建立的任意 dict。`runner/prompts/context.py` 是 Stage Prompt Context 唯一入口，固定 top-level variables：

- `goal`：原始使用者 Goal。
- `stage`：目前 Stage 名稱。
- `task`：Current TODO；沒有時為 `None`。
- `tasks`：正規化 TODO list。
- `workflow`：cycle/progress/validator feedback/shared constraints。
- `validation`：validator path、feedback、額外 validator instructions。
- `project`：project/work path。
- `session`：目前 AI session facts。
- `failure`：目前 attempt/error facts。
- `planning`：Planning 專用正規化 context。
- `previous`：有提供時的上一個 StageResult 摘要。
- `rules`、`always_instructions`：共用規則文字。

Template 禁止直接讀 `state`、`args`、`scratch` 等 Python internal object。

所有 bundled Prompt 統一使用同一個 Jinja loader + `StrictUndefined`。變數缺少或拼錯立即失敗，不允許默默渲染空字串。共用片段與 output contract 可使用 `{% include %}`。

## Stage Prompt Ownership

一般 AI Stage 只需：`workflow/definitions.py` + `prompts/stages/<name>.md`。

Planning 專用的計算 context 直接由 `PlanStage` 處理。普通 AI Stage 只需要 `workflow/definitions.py` 與 `prompts/stages/<name>.md`，不再有 prompt-builder registry。

## Session Policy

- Initial：送完整 Stage Prompt。
- Same-session recovery：只送短 Stage-aware delta，包含目前 Stage 身分、新 failure evidence、需要時的 readonly 提醒與原 output contract/下一步；不重送 session 已知完整 context。
- Fresh/Rebuilt：重新帶 Original Goal、Current TODO（若有）、CURRENT project-state instruction 與完整 Stage instructions。
- Final AI validation 每次 run 使用獨立 fresh session；設定 3 次就一定是 3 個不同 Session。
- Structured-output parse failure 先在 same session 送短 JSON-only correction；若設定 fresh fallback，才建立新 session 並重送完整 Stage Prompt。

Qwen 完整 Prompt 固定透過 stdin 傳入，不放 argv。
