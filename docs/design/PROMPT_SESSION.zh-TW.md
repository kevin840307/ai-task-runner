# Prompt 與 Session 契約

版本：1.2.23

## 通用原則
Fresh/Rebuilt session 必須針對該 stage 自足；Same-session call 只送新增資訊與下一步。這可降低 context 膨脹與 loop 風險，同時保留可恢復性。

## Planning

執行中的 continuation 只要 session 仍可用，就優先重用既有 logical client/session。Planning Understand/Finalize/Judge/Rewrite 維持同一 planning client/session；Executor retry 與後續 TODO 維持主 Executor session；只有 Review 刻意 fresh，Review Finalize 再沿用該 Reviewer session。單次可恢復錯誤不丟 session；invalid session 立即 reset，重複 loop／無進展才 bounded fresh rebuild。程式重啟後的 `--resume` 因舊 Python client 已不存在，才可從 state 重建主 client。
- Understand：優先沿用可用的主 planning session；若沒有可用 session 才 fresh。只允許 bounded project read tools，禁止寫入，也不預塞 `Project files:` tree。
- Finalize/Judge/Rewrite：沿用主工作 session，只送新的指令/feedback。Planning 邏輯上 read-only；Qwen 保留 bounded read tools，且至少保留 `read_file`，避免嚴格 API 收到空 tool set。fresh/rebuilt Planning Prompt 必須自包含。
- Fresh planning fallback：只有目前 planning session 無法恢復時才清 session，沿用同一 planner client，以 full-context Prompt 重新帶 Goal、project root、progress、validator feedback 與可用 inspection summary。
- Judge：沿用目前 Planning client/session，必要時可 bounded read-only inspect；Rewrite 只有 Judge 拒絕後才執行，也沿用同一 session。只有持續異常或 session invalid 才 rebuild。Judge Prompt 同時示範 FAIL/PASS。

## Execution
- Fresh/Rebuilt：Original Goal 只送一次並只作 context/global constraints；Current TODO 是唯一 executable scope。Prompt 只保留跨 stage 安全邊界、Executor 專用規則、shared constraints 與必要的 validator/review recovery evidence；`Run context` 不再重複 scope/session 說明。
- 同 Executor session 的下一個 TODO：使用短 `execution_next_todo` Prompt，只帶新的 Current TODO、scope 提醒與新 feedback。
- 同 TODO retry／Review 修正：使用短 `execution_continue` Prompt。不重送 Original Goal、完整 Task JSON、static rules、舊 output；只帶新的 Review/Validator/Recovery 資訊。

## Review
- Fresh、read-only，只審 Current TODO。會帶 Task/global constraints、Executor evidence 與相關 Validator evidence，但不預先塞入 changed-files 清單，也不帶通用 write/git/shell 規則；只在 acceptance criteria 尚未確認時讀取最小必要的相關檔案。
- 可 resume 的 error 後使用 Same-session Finalize：no tools，直接用已取得 evidence 輸出 JSON verdict。Prompt 同時示範 FAIL/PASS。

## Final Validation
Final AI Validator 固定使用 fresh independent session 並看完整 Goal。File Validator 是 deterministic、與模型無關。

## Rule injection
Project policy 的 `instructions.always` 會附到相關 model call；`instructions.project` 維護在 project agent rule files。相同行為不應再複製到每一份 Prompt template。

Planning 統一保留 bounded read-only Qwen tools，write/edit/shell 等副作用工具仍排除；若某 planning Prompt 已有足夠 context 並要求不再 inspection，模型就不應再使用 read tools。這可讓同一 planning remote session 維持一致 tool policy，也避免空 tools 的 API 相容問題。

## 統一 Recovery 順序
`reuse -> 短 correction/recovery -> 持續失敗或 session 不可用才 rebuild`。Review 是刻意 fresh 的 quality gate；Review FAIL 回原 Executor 修同一 TODO，Review 本身 infrastructure/format 異常先 retry/correction，仍失敗才可 skip。Final Validator 不因 TODO/Review recovery 提前執行。
