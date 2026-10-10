# Regression Workflow 範例

這個可直接執行的 Regression Workflow 只使用目前正式 Stage 契約：

- AI 工作使用 `type: base, profile: execute`。
- Review gate 使用 `type: base, profile: review`，FAIL 只依顯式 `routes.fail` 回到要改善的 Stage。
- Challenge Review 使用 `session_policy: fresh` 做獨立證據檢查。
- Final Validation 使用 `type: ai_validator`，執行 5 個 Fresh Session，至少 3 PASS 才通過。

目前沒有 Repair／Grill／Fix runtime、`repeat` graph control，也沒有舊版 `type: task/review` Stage。Review / Challenge Review FAIL 都只是一般 semantic FAIL reroute。

建議先跑 deterministic mock：

`examples\11_regression_workflow_demo\run_test.bat`

保留 mock 執行後 project state：

`examples\11_regression_workflow_demo\run_mock.bat`

真實 Qwen：

`examples\11_regression_workflow_demo\run_qwen.bat`

所有 launcher 都從全新暫存 repository 副本執行，並印出保留 workspace 路徑供 Debug。

Challenge Review Prompt 只檢查此 demo 明確要求的文件與 E2E 行為，不應把 scope 擴張到無關的 production 題目。
