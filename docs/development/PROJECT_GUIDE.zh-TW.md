# 專案與 AI / 維護者開發指南

版本：1.2.21

## 強制維護規則
1. Generic Runner 禁止 project-specific hardcode。不可為單一 sample/project 寫專案名稱、FAB/ENV/version、filename、business field 或特定 model identity 分支。
2. 同一種行為只能有一份共用 implementation。所有等價流程必須呼叫同一個 helper/function，不得複製 parser/retry/path/snapshot/session 邏輯。
3. 最小程式碼。現有架構能表達就優先刪除/合併，不要再疊 service/helper/framework。
4. 可讀性是要求：命名清楚、function 短且 cohesive、contract 明確、layer 少、不做隱藏魔法。
5. 保留 unrelated behavior；production change 必須只處理已證明的需求。
6. Runner 必須 content-agnostic。Project rule 應放 policy/prompt/validator/project source。

## 修改前檢查
- 是否已有共用 helper 可以直接重用？
- 是否會產生第二套 parser/retry/path/snapshot/session implementation？如果會，先合併。
- Literal 是否只屬於某個 example/project？移出 Runner。
- 這段 code 是當前 evidence 真正需要，還是預先猜未來？刪除 speculative code。
- Same-session Prompt 是否重送 session 已知資訊？移除。
- Fresh/Rebuilt session 是否擁有足夠 context 可以獨立延續？只補缺少部分。
- Executor 是否仍只做 Current TODO？
- Deterministic Validator 是否驗 requirement，而不是 Planner 拆法？
- 真實行為變更後 docs/tests 是否同步？

## 共用入口
CLI/UI/Skill/Python 都應使用 `runner.api.RunRequest` / `runner.api.run()`；不要為 UI/Skill 再建立第二套 orchestration。

## Project policy
所有維護中的 smoke/example project root 都應有 `.ai-task-runner.yaml`。Policy 本身自動 protected。Immutable input/reference fixture 應列成 protected；Task 本來要修改的檔案則不可 protected。

- Session 規則：同一程序內，禁止只為 resume 既有 session 而 new `AgentClient`；必須直接重用原 client。只有程式重啟後的 `--resume` 可從持久化 session state 重建 client。
