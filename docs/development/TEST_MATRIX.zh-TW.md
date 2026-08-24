# 測試矩陣

Version: 1.2.33

## 主要契約
- CLI/API request validation 與 YAML script mode。
- Qwen/OpenCode backend command/session parsing；Qwen stdin-only Prompt + EOF。
- Plan Stage 的 structured task contract、Same/Fresh recovery、minimum TODO contract、bounded scope，以及 no-Understand/no-Judge flow。
- Executor Fresh/Rebuilt Goal context、same-session short continuation、Current-TODO-only。
- Review/read-only/finalize。
- Generic structured result extraction + strict stage schemas。
- Deterministic validator invocation、validator args、timeout/retry、Final AI validation。
- Project policy/protected subtree/snapshot restore/Git guard。
- Debug current/last/bounded history、Terminal single-line render。
- Resume/state/no-progress/recovery。

## Smoke / Examples policy 契約
每個 `examples/*/project` 與 `smoke/*/project` root 都必須有 `.ai-task-runner.yaml`。Policy 本身由 Runner 自動 protected。存在 immutable input/reference 時要明確列 protected；真正要產生/修改的 source/output 仍保持 writable。

## Validator 契約
Example/smoke validator 使用 local `validator_interface.py` report contract。Validator 主要驗 observable deliverable；只有專門測 Runner Planning 的案例才可 assert TODO/state 結構。

## Prompt / Validator 對齊
Smoke/example Prompt 只保留 task-specific requirement，不重複 Runner 已統一處理的自主 inspect、retry、verify 等通用行為。Deterministic validator 不可偷偷增加 Prompt 未寫的格式，也不可綁 Planner 拆法。每個 hard assertion 應對應明確需求或 immutable fixture invariant；像「concise」這種主觀品質，除非 Prompt 有數字上限，否則原則上只做 warning。

## Qwen Live Reliability
`python tool/qwen_live_reliability.py` 是 opt-in 的真實 Qwen 可靠性 gate。它驗證 process restart/resume 沿用 durable session、validator failure 驅動 repair、在衝突 prompt 下的 protected-file policy handling、注入 transient API outage 後在恢復前不替換 session、多 TODO checkpoint resume 不重做已完成工作、YAML List process restart/resume 不重做已完成 item、三個不同 session 的 Final AI 3/2 voting、Python + Final AI mixed validation，以及 bounded timeout recovery。

24 小時 soak 使用 `python tool/qwen_live_reliability.py --hours 24 --pause 30`。Windows 可直接執行 `run_qwen_live_reliability.bat`；無參數時會跑建議的 0.5 小時 high-density gate，傳入參數則完全取代預設，例如 `run_qwen_live_reliability.bat --hours 24 --high-density --require-transient`。要宣稱通過 24H，command 必須真的走完 24 小時 wall-clock duration，且產生 PASS 的 `summary.json`；summary 會記錄 `soak_elapsed_seconds` 作為證據。Fault-injection probes 全綠是很強的 preflight evidence，但不能取代實際經過時間。需要整個 live gate 都覆蓋 Qwen sandbox mode 時，請加 `--sandbox`。收斂階段可使用 `python tool/qwen_live_reliability.py --hours 0.5 --high-density --require-transient`，它會降低 pause、用 `--agent-timeout 180` 與 `--planning-timeout 180` 限制一般 Qwen call，並在短 soak 中混入 Final AI validation、transient API recovery、timeout recovery、YAML List restart/resume，以及週期性 sandbox run；high-density 若未實際覆蓋每一種混合情境就會判定失敗。個別頻率可用 `--soak-final-ai-every N`、`--soak-transient-api-every N`、`--soak-timeout-every N`、`--soak-yaml-every N`、`--soak-sandbox-every N` 調整。每次 run 的 project、精簡 console JSONL、Runner events、state 與 diagnostics 都保存在 `.ai-task-runner-live/<timestamp>/`。
