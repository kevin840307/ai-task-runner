# Prompt 與 Session 契約

版本：1.1.1

## 通用原則
Fresh/Rebuilt session 必須針對該 stage 自足；Same-session call 只送新增資訊與下一步。這可降低 context 膨脹與 loop 風險，同時保留可恢復性。

## Planning
- Understand：fresh session，Goal/project root/progress/rules，只有 bounded project read tools，禁止寫入。不再預塞 `Project files:` tree。
- Finalize：沿用 Understand session、no tools，只送 Plan output contract 與 bounded-TODO rule。
- Fresh minimal fallback：新 no-tool session，重新帶 Goal、project root、progress、validator feedback、成功 inspection summary。
- Refiner/Judge：fresh no-tool session，帶 candidate tasks 與必要 context。Judge Prompt 同時示範 FAIL/PASS。

## Execution
- Fresh/Rebuilt：Original Goal 只送一次並只作 context/global constraints；Current TODO 是唯一 executable scope。Prompt 只保留跨 stage 安全邊界、Executor 專用規則、shared constraints 與必要的 validator/review recovery evidence；`Run context` 不再重複 scope/session 說明。
- Same-session retry：只用短 `execution_continue` Prompt。不重送 Original Goal、完整 Task JSON、static rules、舊 output；只帶新的 Review/Validator/Recovery 資訊。

## Review
- Fresh、read-only，只審 Current TODO。會帶 Task/global constraints、Executor evidence 與相關 Validator evidence，但不預先塞入 changed-files 清單，也不帶通用 write/git/shell 規則；只在 acceptance criteria 尚未確認時讀取最小必要的相關檔案。
- 可 resume 的 error 後使用 Same-session Finalize：no tools，直接用已取得 evidence 輸出 JSON verdict。Prompt 同時示範 FAIL/PASS。

## Final Validation
Final AI Validator 固定使用 fresh independent session 並看完整 Goal。File Validator 是 deterministic、與模型無關。

## Rule injection
Project policy 的 `instructions.always` 會附到相關 model call；`instructions.project` 維護在 project agent rule files。相同行為不應再複製到每一份 Prompt template。

Qwen 的 decision-only stage 在語意上仍是 no-tool：Prompt 明確禁止使用工具。為避免某些 OpenAI-compatible endpoint 拒絕空的 `tools` array，Runner 會保留剛好一個內建唯讀 compatibility tool（`read_file`）可被 discovery，其餘 write、shell、skill、agent、MCP 類與不必要工具仍排除；正常 decision output 不應呼叫這個 compatibility tool。
