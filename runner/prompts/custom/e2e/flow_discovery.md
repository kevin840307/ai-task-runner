{% include "stages/execution.md" %}

# 目標：建立可證明、可直接驅動 Regression Test 的 Business E2E Flow

先讀使用者需求，以及：
- `result/e2e_spec/source_inventory.yaml`
- 使用者指定的 source code / SPEC / config / SQL / workflow 路徑

大型、多專案時可以使用 subagent 分區探索，但主 agent 必須重新核對 evidence。Python inventory 中每個 project 與 entrypoint 都必須標記為「已分析/已映射」或「明確排除」。不可只探索容易看到的部分。

只維護：
- `result/e2e_spec/evidence_index.yaml`
- `result/e2e_spec/flows.yaml`

## Evidence
```yaml
version: 3
evidence:
  - id: EV001
    path: relative/or/absolute/source/path
    symbol: OptionalClassOrMethod
    keywords: [required_keyword_1, required_keyword_2]
    keyword_mode: all      # all | any
    proximity_lines: 120
    claim: 這份證據支持的具體事實
```

## Flow
```yaml
version: 3
source_scope:
  roots: [實際分析的 source roots]
  projects_analyzed: [PRJ_xxx]
  projects_excluded:
    - project_ref: PRJ_xxx
      reason: generated/test-only/明確不屬於 SUT
  entrypoints_mapped: [EP_xxx]
  entrypoints_excluded:
    - entrypoint_ref: EP_xxx
      reason: dev-only/utility/明確不屬於 E2E

  # Python scanner 可能漏掉 legacy/dynamic 入口。只要有可硬驗證 evidence，允許補上。
  additional_projects:
    - id: PRJ_DIRECT_001
      reason: legacy project wrapper 未被 inventory marker 辨識
      evidence_refs: [EV_PROJECT_001]
  additional_entrypoints:
    - id: EP_DIRECT_001
      type: scheduler
      reason: custom scheduler wrapper 未被 Python regex scanner 辨識
      evidence_refs: [EV_SCHED_001]

flows:
  - id: FLOW001
    title: 業務流程名稱
    priority: critical
    trigger:
      description: 真實入口
      evidence_refs: [EV001]
    business_goal: 此流程真正要完成的業務目的
    steps:
      - id: S1
        action: 重要跨模組/服務/狀態步驟
        evidence_refs: [EV002]

    intermediate_states: [READY, PROCESSING]

    business_branches:
      - id: B1
        type: normal
        priority: critical
        claim: 這個分支在業務上代表什麼
        evidence_refs: [EV003]

    outcomes:
      - id: O1
        type: success
        priority: critical
        claim: 可驗證的最終 business outcome
        evidence_refs: [EV004]
        observe_by:
          - id: OBS1
            type: db              # db|api|message|log|file|state|other
            description: 查 ORDERS 最終狀態
            target: ORDERS.STATUS
            sql_ref: SQL_xxx
            evidence_refs: [EV004]
          - id: OBS2
            type: log
            description: 應看到完成流程的 application log
            log_ref: LOG_xxx      # 若 Python inventory 有對應 log candidate
            keywords: ["Order completed"]
            regex: "Order .* completed"   # keyword / regex 至少一種
            correlation_key: request_id    # async/併發時強烈建議
            expected_count: ">=1"
            evidence_refs: [EV005]

    data_effects:
      - id: DE1
        type: db_update           # db_insert|db_update|db_delete|db_select|message_publish|external_call|file_write|state_change|other
        target: ORDERS.STATUS
        evidence_refs: [EV004]

    external_dependencies:
      - id: DEP1
        type: http                # http|mq|kafka|nats|db|file|service|other
        target: Payment API
        ownership: external       # sut|external|unknown
        integration_ref: INT_xxx  # 有 deterministic inventory ref 時填
        evidence_refs: [EV006]

    parameters:
      - inventory_ref: USR_xxx    # scanner 有找到時使用
        source: user              # user|system|config
        role: 決定 NORMAL/HOLD 分支
        values: [NORMAL, HOLD]
      - source: system            # scanner 沒找到也可以，但必須有 direct evidence
        name: RetryCount
        role: retry 次數
        evidence_refs: [EV_PARAM_001]

    behavior:
      retry:
        enabled: true
        description: timeout 時最多重試三次
      idempotency:
        enabled: true
        key: request_id
      transaction:
        expected: atomic

    related_sql_refs: [SQL_xxx]
    related_log_refs: [LOG_xxx]
    related_system_parameter_refs: [SYS_xxx, CFG_xxx]
    related_user_input_parameter_refs: [USR_xxx]
    open_questions: []
```

## Python inventory 的使用規則
`source_inventory.yaml` 是 deterministic candidate discovery，不是 E2E Case，也不是完整性的真理來源：
- `sql_operations`: SELECT / INSERT / UPDATE / DELETE / MERGE / SP 與 table/object。
- `system_parameters` / `config_keys`: 系統參數、環境變數、設定 key。
- `user_input_parameters`: Request / CLI / console 等使用者輸入。
- `integration_candidates`: HTTP / Kafka / NATS / MQ / Scheduler 等整合候選。
- `log_candidates`: logger / logging / Console.WriteLine / print 等可觀測 log 候選。

只有真的影響 Flow、Branch、Outcome 或 Outcome observation 的項目才引用。不要因 SQL 或 log 很多就拆成大量 E2E Flow。

### Scanner 不可反向推論
- Python 找到 candidate：代表『至少存在這個候選』，必須 analyzed/mapped/excluded。
- Python 沒找到 candidate：**不代表不存在**。legacy wrapper、reflection、dynamic SQL、runtime config/topic、factory/DI 都可能漏掃。
- `source_inventory.yaml.scanner_limitations` / `dynamic_candidates` 必須在探索時優先人工/AI 追查。
- 若 scanner 漏掉但 source 有明確證據，使用 `additional_entrypoints/additional_projects` 或 direct `evidence_refs` 建模，不得因缺 inventory ID 放棄真實 Flow。

## Outcome / observe_by 原則
1. Outcome 必須是 Business Outcome，不是 API 200、publish success 或 READY/PROCESSING 這類中間狀態。
2. 每個 Outcome 都必須有 `observe_by`，明確寫「Workflow2 要去哪裡看結果」。
3. 一個 Outcome 可以同時用 DB + API + Message + Log 等多個 observation；多重 observation 通常比單一 DB assertion 更可信。
4. Log 可作為正式 observation。盡量提供 logger/source、keyword/regex、correlation key、expected count，避免只用模糊全文搜尋。
5. 若無法找到可靠 observation，放 `open_questions` 並讓 Review/Grill 挑戰，不要自己猜。

## SUT ownership / Mock 邊界資訊
Flow Discovery 只描述事實，不執行 mock；但 `external_dependencies.ownership` 必須盡量標清楚：
- `sut`: 對應實作/source code 位於使用者指定 SUT 內。
- `external`: SUT 外真正外部 URL / MQ / Kafka / NATS / 第三方 service。
- `unknown`: 證據不足。

Workflow2 會依 ownership 決定 mock boundary；不要因為是 HTTP/MQ 就自動標 external。

## 硬性規則
1. trigger、重要 step、business branch、outcome、observe_by、data effect、external dependency 必須有可驗證 evidence。
2. evidence path 必須真實；symbol/keywords 只能填 source 可搜尋內容。**這是 Hard Gate：path/symbol/keyword 任一宣告錯誤都算假 evidence，必須 FAIL。**
3. 每個 Python 已掃到的 inventory project 必須 analyzed/excluded；每個已掃到 entrypoint 必須 mapped/excluded。但不得把『scanner 沒掃到』解讀成『不存在』。
4. 同一 business lifecycle 不因 DLL/project/service 邊界任意切碎。
5. helper/logger/純 technical call chain 不可獨立成 E2E Flow；但真正用來判定 Outcome 的 log 可以成為 observation。
6. 明確存在 retry、duplicate、failure、boundary、consistency 等 business branch 時必須建模。
7. SQL/table、system/user parameter、log 只當 traceability/observation，不可自動一項一 Case。
8. 找不到足夠證據時列 open question，不要 hallucinate。
9. 不產生 `cases.yaml` 或最終 `e2e_spec.yaml`。

完成前至少反查三次：
- inventory 是否還有未 accounting 的 project / entrypoint？
- 每條 Flow 是否真的走到 Business Outcome，而且 Outcome 有可執行的 observation？
- 是否漏了會改變 branch/outcome 的 SQL state、參數、retry/idempotency/transaction 或 side effect？
