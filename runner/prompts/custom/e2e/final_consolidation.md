{% include "stages/execution.md" %}

# 目標：只組裝最終 E2E SPEC；不得改寫已驗證 business truth

讀取：
- `result/e2e_spec/flows.yaml`
- `result/e2e_spec/cases.yaml`
- `result/e2e_spec/evidence_index.yaml`
- `result/e2e_spec/source_inventory.yaml`

產生 `result/e2e_spec/e2e_spec.yaml`。

Python Final Gate 會對 Flow / Case / Evidence 做 canonical deep equality。Final Stage 可以排序與加 summary，但不能修改 outcome、observe_by、data effect、dependency ownership、parameter、branch 或 case assertion reference。

格式：
```yaml
version: 3
metadata:
  purpose: Evidence-driven E2E regression specification
flows: []
cases: []
evidence: []
coverage:
  total_flows: 0
  critical_flows: 0
  flows_with_cases: 0
  business_branches_total: 0
  business_branches_covered: 0
  outcomes_total: 0
  outcomes_covered: 0
open_questions: []
```

Final 只做：
- assemble
- coverage summary
- open question summary
- presentation-friendly ordering

不要在 Final 修正 Stage 1/2 business truth；發現真實錯誤就 FAIL，讓 recovery 回來源 Stage/repair。
