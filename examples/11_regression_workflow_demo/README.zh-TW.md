# Regression Workflow Demo (Runner 1.2.41+)

這個範例只使用目前 Runner 已存在的 Workflow 能力：BaseStage、recover、`previous.data`、cached client/session、Final AI voting。

## Skill 數量

只有 10 份：6 個業務 Action + 共用 `review.md`、`grill.md`、`fix.md`、`final_validation.md`。

## Session 設計

- `run_prompt` 與所有 Fix：共用 Writer client/session。
- `review`：使用 `review_client`，所有 Review 共用自己的 session。
- `grill_ai`：使用 `grill_client`，所有 Grill 共用自己的 session。
- Final Validation：5 次，每次 `fresh_session_each_run: true`，3/5 PASS 即通過。

Skill 不重複貼完整 Goal、歷史或 Review feedback。Recover 的 `fix.md` 直接讀 Runner 1.2.41 提供且有大小限制的 `previous.data`。

## 測試

從專案根目錄執行：

`examples\10_regression_workflow_demo\run_mock.bat`

Mock 會故意讓 Project Documentation 第一次 Grill FAIL，用來驗證：

`Grill FAIL -> previous.data -> generic Fix -> same Writer session -> Grill again -> PASS`

真實 Qwen：

`examples\10_regression_workflow_demo\run_qwen.bat`
