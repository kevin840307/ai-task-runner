
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

Project / Runtime polling 採 non-overlapping：上一個 request 完成後才排下一輪。Windows 每次 Project list refresh 只取得一次 `tasklist` PID snapshot，再由所有已追蹤 Project 共用。Workflow Generator status polling 也採相同規則，避免瀏覽器或主機較慢時堆疊 request。

## UI/UX polish
- Running indicator 使用純 CSS activity line/pulse，與 Runtime polling 解耦，低頻 polling 仍保持視覺流暢。
- Runtime 顯示 Last update；超過約 30 秒未有新狀態時以 Warning 呈現。
- Workflow Studio 保留 dirty-state 離開保護：切檔、切專案、切模式、Reload、離頁都不會靜默丟失修改。
- 錯誤預設顯示摘要；Details 才開啟完整錯誤 Modal，避免 Background Runner 錯誤中斷操作。
- Runtime / Project / YAML status 使用一致狀態 icon 語意。
- Header、字級、圓角與 shadow 已收斂為較緊湊的 engineering-tool density；聊天與輸入字級同步縮小。

- **Live Runtime 回饋** — 任務 Running 時，Runtime footer 會以瀏覽器本地 timer 每秒更新 `Elapsed HH:MM:SS`，不增加後端 polling；正在執行的 Project 列也會直接顯示目前 Stage 與 Progress，點擊即可回到該 Runtime。

### 可攜式 Workflow Folder

放在專屬 Custom 子資料夾的 Workflow，可以匯出成 `.workflow-folder.zip`。Folder package 有明確 ownership 邊界：

- Workflow 的 Prompt 只允許引用「自己的 Custom folder」、`custom/common`、或 System/Stage Prompt。
- Export 只把自己的 Prompt 打包；`custom/common` 與 System Prompt 只記錄成 dependency，不複製進 package。
- Export 會把相同 ownership 的 **Workflow folder + Prompt folder 整個遞迴打包**，不再只挑 YAML / Markdown。`.py` validator、`.json` / schema、`.j2`、example、asset、binary support file、巢狀子資料夾都會原樣保留；只排除明確的 cache/runtime/temp 產物，並拒絕 symlink。
- `custom/common` 與 System 只記為 dependency，不會被打包。Import 會先驗證 dependency，再只替換相同 logical folder 的 Custom Workflow folder 與 Custom Prompt folder，完整還原所有 owned files；`custom/common` 與 System 永遠不刪除、不覆蓋。舊版 v1 folder package 仍可匯入。
- Import 或驗證途中失敗，兩個自己的 folder 都會完整 rollback。

### Flow Map

Workflow Studio 的 **+ Stage** 旁新增 **Flow Map**。這是唯讀流程圖，會顯示正常 Flow、FAIL/Recover 路徑與 `restart_at` 回跳；只存在於 recover 的 Stage 也會顯示。點 Stage 節點可看 Type、Prompt、Incoming 與 Outgoing routing。

### AI Workflow Builder target

Generate with AI 現在在 Generate 前直接指定 **Folder + Filename**；Ready 編輯頁會持續顯示 target path，Save 視窗也使用同一組 Folder/Filename 並提供目的路徑預覽。Custom 會發布到 `runner/workflow/custom/<folder>/<filename>`，owned generated files 放在 `runner/prompts/custom/<folder>`。
