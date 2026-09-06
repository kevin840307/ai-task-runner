
## 環境檢測

Run options 內提供 **Check environment**。UI 直接呼叫同一份可從命令列使用的 `tool/environment_check.py`，檢查本機 Python 版本/套件、必要 Runner 檔案、UI data 寫入權限，以及 Qwen/OpenCode 執行檔是否可從 PATH 找到。Backend 未安裝只列為 warning，因為使用者可能只使用其中一種 Backend。

Stage Editor 以行為分組呈現參數，不把 YAML 欄位全部平鋪。`max_attempts` / `on_exhausted` 放在 **Recovery gate**，並提供精簡 Behavior 預覽；一般 AI-backed 的 `base`、`task`、`review` 與 `ai_validator` 都能從 Visual UI 新增 `runs` / `required_passes`。`continuation_prompt` 刻意維持 YAML-only advanced override，讓 Visual UI 只保留一個 Prompt selector。
