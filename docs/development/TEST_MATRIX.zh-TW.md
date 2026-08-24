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
