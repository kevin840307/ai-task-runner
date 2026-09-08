{% include "stages/execution.md" %}

# 目標：只從已通過的 Flow / Branch / Outcome / Observation 生成 E2E Cases

先讀：
- `result/e2e_spec/flows.yaml`
- `result/e2e_spec/evidence_index.yaml`
- `result/e2e_spec/source_inventory.yaml`

維護 `result/e2e_spec/cases.yaml`：
```yaml
version: 3
cases:
  - id: E2E001
    title: Case 名稱
    flow_ref: FLOW001
    type: happy_path
    priority: critical
    business_reason: 為何值得 Regression
    preconditions: []
    trigger: 真實觸發方式
    branch_refs: [B1]
    expected_path: []
    expected_outcome_refs: [O1]
    observation_refs: [OBS1, OBS2]
    evidence_refs: [EV001, EV004]

    sql_assertions:
      - inventory_ref: SQL_xxx   # scanner 有找到時使用
        expectation: 真正需要驗證的 INSERT/UPDATE/SELECT 結果
      - target: LEGACY_TABLE.STATUS   # dynamic SQL scanner 漏掉時，改用 direct evidence
        operation: update
        evidence_refs: [EV_SQL_DIRECT]
        expectation: STATUS 應由 RUNNING 變 DONE

    parameter_variations:
      - inventory_ref: USR_xxx
        value_class: valid|boundary|invalid|special
      - name: LegacyMode
        evidence_refs: [EV_PARAM_DIRECT]
        value_class: special
```

規則：
1. 每個 Flow 至少有 Case；critical Flow 至少有 happy_path。
2. `branch_refs` 只能引用 Stage 1 已證明的 branch；不可偷創 branch。
3. `expected_outcome_refs` 只能引用該 Flow outcome；API 200 / function return 不足以取代 Business Outcome。
4. `observation_refs` 必須引用所選 Outcome 的 `observe_by`；每個 Case 都要明確知道最後去哪裡 assert。
5. Log observation 是正式 assertion 來源之一；async/log-heavy 系統可用 correlation id + keyword/regex + count 判斷，但不要只用「有任何 log」作 PASS。
6. critical branch / critical outcome 必須 100% cover；全部 branch/outcome 目標至少 90%。
7. SQL/table/system parameter/user parameter 只在會改變 path、outcome、資料一致性或 Regression 風險時形成 assertion/variation。
8. 沒有 evidence 不要硬生 retry/idempotency/failure/boundary。
9. Case 必須 materially distinct，避免 case explosion。
10. 若發現 Stage 1 真實錯誤，回報需要回前一 Stage，不要偷偷改 `flows.yaml`。

完成前反查：
- branch/outcome 是否漏 Case？
- 每個 Case 是否真的驗到 Business Outcome，而且 observation 足以辨識該次執行？
- DB / log / message / API assertion 是否只是中間成功訊號，而非真正結果？


## Inventory ref 規則
- inventory_ref 有填：Python 必須找到該 ref，填錯就是 FAIL。
- scanner 沒找到但 source 有真實證據：可不用 inventory_ref，改用該 assertion/variation 的 `evidence_refs`。
- 不得因為 SQL/parameter 沒有 inventory ID 就刪掉一個有 source evidence 的 Case。
