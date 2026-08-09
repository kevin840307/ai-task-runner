# 測試矩陣

Version: 1.1.1

## 主要契約
- CLI/API request validation 與 YAML script mode。
- Qwen/OpenCode backend command/session parsing；Qwen stdin-only Prompt + EOF。
- Planning same-session/fresh fallback、Judge-before-rewrite、Planner session rewrite reuse、至少 6 TODO、bounded scope、planning quality-gate fail-soft。
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
