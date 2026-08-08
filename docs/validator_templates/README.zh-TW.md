# Validator Interface 與範本

版本：1.1.1

Example/smoke 的 deterministic validator 統一使用 local `validator_interface.py` 模式。Project-specific check 留在 validator；interface 只統一 report/error/warning/exit 行為。

Runner 呼叫 file validator 時固定加入 `--project-root <root> --state-file <state>`，之後把所有可重複 `--validator-arg` 原樣附加。因此 validator 可自行新增 argparse option（例如 `--fab`），不需要修改 Runner。

好的 Validator 應驗 observable requirements、只用 deterministic local operation、產生可修復的 failure，且不能修改 answer fixture 來讓自己 PASS。除非該 smoke 明確在測 Planning，否則不應限制 Planner TODO 數量/標題/拆法。
