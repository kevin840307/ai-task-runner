# 測試矩陣

這份文件區分 deterministic CI 已覆蓋項目，以及仍必須用 real backend / soak 實跑的項目。

## Deterministic CI

一般 GitHub gate 會跑 Ubuntu + Windows compile/pytest，以及 React Studio build。CI 也會重新建置 Workflow Editor，並驗證已提交的 `ui/static/workflow-studio-app` 與 `ui/studio-src` 完全一致；CI 只做 verify，不會自行改寫 branch。

| 區域 | 覆蓋 |
| --- | --- |
| Workflow schema | Stage type/options、未知欄位拒絕、只允許 PASS/FAIL route、target 存在性、task-scope topology |
| Semantic routing | PASS next、顯式 PASS/FAIL、done/stop、backward loop、未 routing FAIL 安全停止 |
| Technical ERROR | Stage/global retry、無限 `-1`、Same Session retry、Fresh Session rotation、partial-write recovery、Review finite-retry fail-soft Skip、非 Review finite exhaustion fail-closed、KeyboardInterrupt/SystemExit 不被吞掉 |
| Session policy | main/role/fresh、非法 mode、role durable restore/persist、fresh 不持久化、單一 role reset、global reset、錯誤後 session rotation |
| Dynamic Handoff | target allow-list、非法 target、一次只選一個 target、role -> coordinator、final validator FAIL -> coordinator、durable resume |
| Prompt | Dynamic shared worker 會 render role `instructions`；prompt category ownership；共用 retry/continue/recover control envelope |
| Validator | File command validator、AI validator、多 validator 任意位置、多次 AI vote、validator FAIL rollback |
| Task production | Plan Task[]、custom command/Python `produces: tasks`、連續 task scope |
| Resume/state | workflow position、task step、transition_previous、role Sessions、損壞 state 拒絕 |
| Dry Run | 正常 closure、FAIL loop、Dynamic Handoff、自訂 Task producer、non-converging cutoff、非法 schema/route |
| Stage Probe | 隔離 Real Stage 真實 backend 呼叫、固定 Prompt Agent Ping、bounded test retry safety、回傳 result/next target 且不繼續 workflow |
| Studio backend | YAML graph save/validate、Stage CRUD、asset root、prompt reference、Stage test sandbox |
| Studio React | PASS/FAIL/Handoff handle、Palette 搜尋、安全 Duplicate、Review max_failures UI、Dynamic branch layout、session-policy UI 防呆、沒有 ERROR edge、Workflows/Prompts/Settings 分離導覽、Stage Form/YAML/Routing/Test ownership、常見桌面解析度 overflow 檢查 |
| Process/runtime | ownership/orphan/supervisor/control-file probes、同 checkpoint 重複 crash 持續 restart、capped process backoff |

## 負向 / 已移除契約

測試必須拒絕或證明不存在：

- `routes.error`；
- repair/recover/restart_at/repeat/max_attempts/on_exhausted graph control；
- 不存在 Discussion / Group Chat runtime 或 UI mode；
- 已刪 compatibility runtime module；
- 舊 Workflow/Prompt asset path。

## Tool Workflow Preflight

`tool/workflow/` 代表性 YAML 必須能被 production loader 載入，並相容 `tool/workflow_dryrun.py`。目前範例只使用 Review gate、Validator 與 custom task production，不存在 Grill runtime 契約。

## real-Qwen 短 gate

real backend proof 使用：

```powershell
tool\qwen_live_reliability_0_5h.bat
```

在 soak 前會先跑 deterministic preflight，再跑 real-Qwen：

- file / AI / mixed topology；
- Dynamic Handoff target 選擇；
- main / reusable role / fresh session policy；
- 同一 role 被再次選中時必須沿用相同 Session；
- Review FAIL rollback 與 durable `max_failures` 第四次進入 bypass/reset；
- Validator FAIL rollback；
- HTTP 429 / 502 / 503；
- raw disconnect；
- expired Session -> Fresh Session；
- process restart / detached UI resume；
- YAML List resume；
- custom Stage / custom Task producer；
- protected-file policy；
- timeout/recovery budget；
- final AI voting。

「script 有 probe」不代表「probe 已 PASS」。要宣稱 live reliability 必須保留該次 run directory / summary。

## 24H 驗收

短 live gate PASS 後再跑：

```powershell
tool\qwen_live_reliability_24h.bat
```

24H 必須有完整 wall-clock evidence，並確認：

- ownership lock 不會卡死；
- stop/crash/resume 後沒有 orphan process；
- state/log 不會無限成長；
- committed workflow/task position 不遺失；
- role Session 不損壞；
- resume 時 frozen Workflow/Prompt resource 穩定。

Deterministic CI、短 live gate、24H soak 是三個不同的信心層級。

- Workflow Library 右鍵 Chat 顯示切換（顯示/隱藏）與 Chat picker 即時過濾。
- 沒有有效已保存 Workflow 偏好時，Chat 預設選擇 `ralphy_ai_validate.yaml`。
- 主導覽分離 Workflows / Prompts，不額外顯示重複的 Settings nav。
- Stage Editor 契約為 `Form | YAML | Routing | Test`，Stage YAML 共用既有 source parser。
- 桌面 browser layout/context-menu smoke：1024、1280、1366、1440、1920 寬度。
