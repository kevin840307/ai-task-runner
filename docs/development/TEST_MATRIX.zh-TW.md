# 測試矩陣

Version: 1.2.61

## 主要契約
- CLI/API request validation 與 YAML script mode。
- Qwen/OpenCode backend command/session parsing、兩者 stdin-only Prompt + EOF、OpenCode permission sandbox/mode policy。
- Plan Stage 的 structured task contract、Same/Fresh recovery、minimum TODO contract、bounded scope，以及 no-Understand/no-Judge flow。
- Executor Fresh/Rebuilt Goal context、same-session short continuation、Current-TODO-only。
- Review/read-only/finalize。
- Generic structured result extraction + strict stage schemas。
- Deterministic validator invocation、validator args、timeout/retry、Final AI validation。
- Project policy/protected subtree/snapshot restore/Git guard。
- deterministic 損壞／不相容 Resume state 必須 fail-fast；Goal／Final-AI Prompt durable resource（含 YAML child source 刪除後 Resume）需覆蓋。
- Debug current/last/bounded history、Terminal single-line render。
- Resume/state/no-progress/recovery。

## Smoke / Examples policy 契約
每個 `examples/*/project` 與 `smoke/*/project` root 都必須有 `.ai-task-runner.yaml`。Policy 本身由 Runner 自動 protected。存在 immutable input/reference 時要明確列 protected；真正要產生/修改的 source/output 仍保持 writable。

## Validator 契約
Example/smoke validator 使用 local `validator_interface.py` report contract。Validator 主要驗 observable deliverable；只有專門測 Runner Planning 的案例才可 assert TODO/state 結構。

## Prompt / Validator 對齊
Smoke/example Prompt 只保留 task-specific requirement，不重複 Runner 已統一處理的自主 inspect、retry、verify 等通用行為。Deterministic validator 不可偷偷增加 Prompt 未寫的格式，也不可綁 Planner 拆法。每個 hard assertion 應對應明確需求或 immutable fixture invariant；像「concise」這種主觀品質，除非 Prompt 有數字上限，否則原則上只做 warning。

## Qwen Live Reliability
`python tool/qwen_live_reliability.py` 是 opt-in 的真實 Qwen 可靠性 gate。它驗證 process restart/resume 沿用 durable session、validator failure 驅動 repair、在衝突 prompt 下的 protected-file policy handling、注入 transient API outage 後在恢復前不替換 session、多 TODO checkpoint resume 不重做已完成工作、YAML List process restart/resume 不重做已完成 item、三個不同 session 的 Final AI 3/2 voting、File + Final AI mixed validation，bounded timeout recovery（即使 sandbox stderr 每次不同仍維持穩定 failure identity）、每個 case 使用不同 prompt marker 以降低 prompt cache 掩蓋真實情境，以及 API 真正斷線 180 秒後自動以同 session 恢復。 另外會明確實跑 builtin `file`/`ai`/`mixed` topology；來源 YAML 使用簡化的 Plan flow，但 Loader normalization 必須仍得到 `planning -> execute -> review -> validator`，並從 model prompt history 稽核 Same/Fresh transport 是否 bounded、強制單一最終驗收 TODO 走 Review FAIL -> Repair，並確認 Repair 只取得 bounded Review feedback 而不是整份 Review contract，並強化 validator failure recovery：Repair Plan 必須使用不同的 Fresh Planning Session，且 Prompt 只包含必要的 Goal + validator evidence。 現在在任何真實模型呼叫前，會先跑 deterministic Workflow Dry Run preflight，涵蓋 builtin `file`/`ai`/`mixed`、自訂 command-backed Python Task Producer，以及含 `repeat` / `recover` / `restart_at` 的 synthetic 12-Stage composability SOP，並鎖定 Qwen `consecutive_identical_tool_calls` loop 訊號必須被診斷且觸發 Fresh Session reset。另新增真實 Qwen `command -> produces: tasks -> scope: task -> command file validator` probe，直接證明 Task Producer 不依賴 PlanStage。

24 小時 soak 使用 `python tool/qwen_live_reliability.py --hours 24 --pause 30`。Windows 可直接執行 `run_qwen_live_reliability.bat`；無參數時會跑建議的 0.5 小時 high-density gate，傳入參數則完全取代預設，例如 `run_qwen_live_reliability.bat --hours 24 --high-density --require-transient`。要宣稱通過 24H，command 必須真的走完 24 小時 wall-clock duration，且產生 PASS 的 `summary.json`；summary 會記錄 `soak_elapsed_seconds` 作為證據。Fault-injection probes 全綠是很強的 preflight evidence，但不能取代實際經過時間。需要整個 live gate 都覆蓋 Qwen sandbox mode 時，請加 `--sandbox`。收斂階段可使用 `python tool/qwen_live_reliability.py --hours 0.5 --high-density --require-transient`，它會降低 pause、用 `--agent-timeout 180` 與 `--planning-timeout 180` 限制一般 Qwen call，並在短 soak 中混入 Final AI validation、transient API recovery、timeout recovery、YAML List restart/resume，以及週期性 sandbox run；high-density 若未實際覆蓋每一種混合情境就會判定失敗。每個產生的 live probe 都會在 prompt 第一行加入 case-specific marker，避免大量案例共用完全相同的 prompt prefix。獨立 long API probe 預設會把本機 proxy 直接斷線 180 秒，可用 `--long-api-outage-seconds N` 調整。個別頻率可用 `--soak-final-ai-every N`、`--soak-transient-api-every N`、`--soak-timeout-every N`、`--soak-yaml-every N`、`--soak-sandbox-every N` 調整。加上 `--example-smoke-project` 會在 reliability probes/soak 最後複製並執行 `examples/01_basic_command_validator/project` 作為真 agent smoke；也可以傳入其他 project path。若該 example 需要 custom workflow，另加 `--example-smoke-workflow path/to/workflow.yaml`，例如 `tool/workflows/skill_prompt_review_chain.yaml`。要更廣覆蓋，可重複傳入 `--example-smoke-matrix-project` 與 `--example-smoke-matrix-workflow`，在 probes/soak 後交叉實跑真實 example project 與 workflow YAML。這是 opt-in，避免改變既有 soak 預設。每次 run 的 project、精簡 console JSONL、Runner events、state 與 diagnostics 都保存在 `.ai-task-runner-live/<timestamp>/`。

Matrix command 範例：

```powershell
python tool/qwen_live_reliability.py --hours 0.25 --high-density --require-transient --example-smoke-matrix-project examples/01_basic_command_validator/project --example-smoke-matrix-project examples/10_skill_prompt_review_workflow/project --example-smoke-matrix-workflow runner/workflow/builtin/file.yaml --example-smoke-matrix-workflow runner/workflow/builtin/mixed.yaml --example-smoke-matrix-workflow tool/workflows/skill_prompt_review_chain.yaml
```

Windows 便利 BAT 放在 `tool/`：`qwen_live_reliability_0_5h.bat` 是目標 95% 信心度的 preflight；`qwen_live_reliability_24h.bat` 是跑滿 24 小時後目標 99.99% 信心度的 soak。這些百分比是 PASS 後的信心目標，不是無條件保證；實際證據仍以輸出的 `summary.json` 為準。99.99% 是工程信心目標，不是由單次 24 小時執行統計證明的失敗機率。

- Worker Supervisor regression 需涵蓋依 durable state directory 清理 Direct/YAML child orphan process。
- StageExecutor regression 需確認 `KeyboardInterrupt` / `SystemExit` 直接往上傳遞，不進入 retry/recovery。
- Stage capability regression 需涵蓋 `retry: 0` 直接升級 Fresh Session、`skip_on_error: false`、`track_changes` exposure，以及 process-backed Stage 共用的直接 `retry` / `skip_on_error` / `track_changes` 選項。
