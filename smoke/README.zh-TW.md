# Smoke 測試

版本：1.1.1

Smoke project 用來驗小型 deliverable 與 Runner/backend 關鍵行為。每個 smoke `project/` root 都有 `.ai-task-runner.yaml`；immutable input/reference 會 protected，真正要實作/輸出的檔案保持 writable。Deterministic validator 統一使用 `validator_interface.py`。

`qwen_single_prompt_todo_split` 因為測試目的就是 Planning decomposition，所以刻意會檢查 Runner task state；其他 smoke validator 應驗 deliverable correctness，不應綁 Planner 拆法。

Smoke Prompt 只描述該案例真正要測的行為。Validator 應驗 observable deliverable，不可額外加入 Prompt 沒寫的隱藏格式；只有 TODO-split smoke 刻意驗 Runner planning state。

Smoke starter 不可夾帶上次執行的 state、generated output、validator report、model rule copy 或 bytecode cache；只有刻意保留的 immutable fixture 例外。
