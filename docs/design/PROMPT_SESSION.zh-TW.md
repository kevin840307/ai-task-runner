# Prompt 與 Session 契約

## Prompt Variables

Prompt 變數是正式 contract，不是各 Stage 自行建立的任意 dict。`runner/prompts/context.py` 是 Stage Prompt Context 唯一入口，固定 top-level variables：

- `goal`：原始使用者 Goal。
- `stage`：目前 Stage 名稱。
- `task`：Current TODO；沒有時為 `None`。
- `tasks`：正規化 TODO list。
- `workflow`：Stage Template 真正需要的 cycle 與 validator feedback。
- `validation`：validator path、feedback、額外 validator instructions。
- `project`：project root。
- `previous`：上一個 Stage 的 bounded handoff（`stage`、`status`、bounded `output`、bounded structured `data`）。Recover Prompt 應只使用 `reason`／`missing_items` 等具體新 feedback，不得重建或重送無關 Context。
- `planning`：Planning 專用的 progress / inspection context。
- `rules`、`always_instructions`：共用規則文字。


Recover Prompt 範例：
```jinja2
{% if previous.data %}
Review feedback: {{ previous.data | tojson }}
{% endif %}
```

Template 禁止直接讀 `state`、`args`、`scratch` 等 Python internal object。

所有 bundled Prompt 統一使用同一個 Jinja loader + `StrictUndefined`。變數缺少或拼錯立即失敗，不允許默默渲染空字串。共用片段與 output contract 可使用 `{% include %}`。

## Stage Prompt Ownership

一般寫入型 AI 工作優先使用語意化 `type: task`；唯讀 verdict 工作使用 `type: review`。只有真的需要 BaseStage 預設行為的自訂 AI Stage 才使用 `type: base`。

Planning 專用計算 context 由 `PlanStage` 處理。`TaskStage` 與 `ReviewStage` 只是共用 AI Stage implementation 上的薄語意 profile；Review 預設擁有 readonly mode 與 structured verdict parser。Review Prompt 必須根據可用 evidence 回傳 verdict，不得修復、搜尋工具或要求不存在的工具。不再有 prompt-builder registry。

## Session Policy

- Initial：送完整 Stage Prompt。同一 Session 之後再次遇到同一份 Stage Prompt contract 時，system Stage 可使用設定的 `continuation_prompt`，只補新的 TODO/evidence，不重送該 Session 已知的 Goal/rules。
- Same-session recovery：只送短 Stage-aware delta，包含目前 Stage 身分、新 failure evidence、需要時的 readonly 提醒與原 output contract/下一步。Read-only recovery 會明確禁止 write/shell/edit/tool-discovery 動作，讓重複工具或 timeout failure 收斂回 Stage output contract；不重送 session 已知完整 context。
- Fresh/Rebuilt：只加一段很短的 recovery header，再重送原始完整 Stage Prompt。Goal、Task、Rules 由 Stage Prompt 本身負責，wrapper 不重複。
- Final AI validation 每次 run 使用獨立 fresh session；設定 3 次就一定是 3 個不同 Session。
- Structured-output parse failure 先在 same session 只送 parser feedback + JSON-only correction；若設定 fresh fallback，才建立新 session 並重送完整 Stage Prompt。

完整 AI task Prompt 固定透過 stdin 傳入，禁止塞進 argv。Qwen `/context` 與 `/compress-fast` 是短 backend control command，不是 task Prompt，因此可以走 CLI control-argument path。

## Prompt Size Rules

- Global engineering / safety rules 放在共用 rules，不重複塞進每個 TODO acceptance criterion。
- Planning 只產生 task-specific、可客觀驗證，且針對該 TODO 產出 artifact / behavior 的 acceptance criteria；不得把未來 Stage、review、repair、validator 結果當作 acceptance criteria。
- Planner 可見 Stage catalog 中只要有 write Stage，每個 planned TODO 就必須至少包含一個 write Stage；read-only review-only TODO 會被拒絕。
- Stage Prompt 優先使用短而明確的 scope / evidence / action / contract，不重複同義規則，也避免過長的問題列舉。
- JSON output 範例刻意保留，因為對小模型 structured output 穩定度有實際幫助。
