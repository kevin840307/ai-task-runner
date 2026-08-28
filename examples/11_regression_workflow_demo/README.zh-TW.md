# Regression Workflow 範例（Runner 1.2.43+）

可直接執行的六階段流程：Project Discovery → Documentation → E2E SPEC → Verification Design → Regression DSL → Execution & Qualification；中間包含 Review／Grill recovery gate，最後使用 5 個 Fresh Session AI 驗證，3 PASS 即通過。

範例會故意讓第一次 Documentation Grill FAIL。`fix.md` 必須收到 bounded `previous.data`、修正缺口，再回到同一個 Grill Session。Review／Grill 在同 Session 已看過完整 contract 後，只透過 continuation prompt 傳新的 target／evidence，不重送完整規則。

建議先跑 deterministic mock 驗證：

`examples\11_regression_workflow_demo\run_test.bat`

若要保留 mock 執行後的 project state：

`examples\11_regression_workflow_demo\run_mock.bat`

真 Qwen：

`examples\11_regression_workflow_demo\run_qwen.bat`

所有 BAT（`run_example`、`run_qwen`、`run_mock`、`run_test`）都會從全新的暫存 repository 副本執行，並印出保留的 workspace 路徑供 Debug。

## Grill 範圍

這是一個簡單範例。Grill-AI 只檢查 Project Documentation 與 E2E SPEC 明確列出的必要項目，不得擴大到部署、監控、擴縮、Rollback、UI/Mobile、IoT 等非本範例需求，也不可因輕微文字或風格問題判定 FAIL。

