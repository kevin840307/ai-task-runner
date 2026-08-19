Review only. Do not modify files.

確認指定 XXX 方塊的 E2E Regression Test：

- 有涵蓋重要不同參數與行為。
- 適用時有 Condition Y/N、Boundary、Error、Known Issue。
- 沒有只換資料但邏輯相同的重複 Case。
- 每個 Case 都有實際 E2E 執行與 Validation。
- SQL / DB 沒有使用 Mock。
- prepare.sql 沒有直接建立預期結果或偽造執行結果。
- 沒有 hardcode、繞過 Scheduler、為了 Coverage 製造無意義 Case。
- Python Validator 的 Function Coverage 已通過。

不要要求固定 Case 數量。
以最少且有意義的 Case 為原則。

PASS only when tests are meaningful, non-duplicated, validated, and not cheating.

Return exactly:

{
  "decision": "PASS" | "FAIL",
  "summary": "short reason",
  "missing_items": []
}