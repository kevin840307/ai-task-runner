
## 環境檢測

Run options 內提供 **Check environment**。UI 直接呼叫同一份可從命令列使用的 `tool/environment_check.py`，檢查本機 Python 版本/套件、必要 Runner 檔案、UI data 寫入權限，以及 Qwen/OpenCode 執行檔是否可從 PATH 找到。Backend 未安裝只列為 warning，因為使用者可能只使用其中一種 Backend。

Stage Editor 以行為分組呈現參數，不把 YAML 欄位全部平鋪。`max_attempts` / `on_exhausted` 放在 **Recovery gate**，並提供精簡 Behavior 預覽；一般 AI-backed 的 `base`、`task`、`review` 與 `ai_validator` 都能從 Visual UI 新增 `runs` / `required_passes`。`continuation_prompt` 刻意維持 YAML-only advanced override，讓 Visual UI 只保留一個 Prompt selector。

## Theme 與外觀

UI 內建三種配色，並將 Light/Dark 外觀獨立控制。

- 預設：`Teal + System`
- Appearance：`System`、`Light`、`Dark`
- Theme：`Teal`、`Deep Blue`、`Violet`、`Amber`、`Rose`

Theme 只改變背景、Surface、選取狀態、Border、文字與主 Accent。Runtime 語意色固定不隨 Theme 改變：Running/Info 為藍色、PASS/Success 為綠色、Warning 為琥珀色、Error/Danger 為紅色。

設定會保存在瀏覽器 localStorage，並在主樣式載入前套用，避免重開 UI 時出現明顯閃色。`System` 會跟隨 OS/瀏覽器 `prefers-color-scheme`，UI 開啟期間系統模式切換也會同步更新。


## Custom 子資料夾

Workflow / Prompt 的 `custom/**` 會遞迴掃描。新增 Workflow / Prompt 時可選既有子資料夾，或直接建立如 `e2e/regression` 的新資料夾；`../`、絕對路徑等跳出 Custom root 的路徑會被拒絕。


## 介面語言與側邊欄

- UI 預設使用繁體中文（`zh-TW`）；產品名、Page Title、Workflow/Stage 等技術名稱可維持原名。
- `Theme / Appearance` 面板可切換 `繁體中文 / English`，設定會保存於瀏覽器。
- 左側 Tasks / Workflows 使用圖示導覽並縮小高度；新增專案改由 `專案` 標題右側的 `+` 開啟原本的 Open Project dialog。

## 語言與離線 UI

UI 預設使用繁體中文說明，並可切換 English。`Appearance`、`Theme`、`Workflow`、`Stage`、`Settings`、`Control`、`Backend` 等常見系統/技術名稱維持英文；操作說明、help text、tooltip、Behavior Preview 等描述性文字依語言切換。

UI 以完全離線、本機使用為前提。Runtime UI 不依賴 CDN、Google Fonts、遠端 JavaScript/CSS 或翻譯 API；所需靜態資源都必須隨專案一起提供。測試會拒絕 UI static assets 引入遠端 runtime resource URL。
