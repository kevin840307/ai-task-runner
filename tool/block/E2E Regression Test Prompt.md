請產生 XXX 方塊的 E2E Regression Test。

請自行分析現有 VB.NET Source、方塊文件、問題文件、DDL 與相關 Scheduler SOP。

輸出：

Root/
- Global/
  - Create SOP.sql
  - Create Condition.sql
  - Create Action.sql
  - Validation.sql
- XXX/
  - XXX.vb
  - XXX-SOP-001/
    - prepare.sql
  - XXX-SOP-002/
    - prepare.sql

要求：

- 產生 XXX 不同且有實際意義的 E2E Regression Test。
- 考慮重要參數、Condition Y/N、Boundary、Error 與 Known Issue。
- 相同邏輯 Case 去重，不可只因資料值不同就重複。
- Web / MQ 可以 Mock。
- SQL / DB 禁止 Mock，依 Source 與 DDL 產生真實 prepare.sql。
- prepare.sql 只能建立測試前置資料，不可直接建立預期結果或偽造執行結果。
- 每個 XXX-SOP-* 必須真正執行並有 Validation 結果。
- 測試必須實際覆蓋 XXX 重要 Function。
- 不可修改 validation.py、AI validator、Function Mapping 或原始輸入資料。
- 完成後執行：
  python validation.py --block XXX
- Validator FAIL 時修復後重新驗證。

Python Validator 與 AI Validator 都 PASS 才算完成。