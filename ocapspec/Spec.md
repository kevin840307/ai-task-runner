## 摘要
在 Tasks Board/List 增加 All、Running、Completed、Failed 單選篩選，預設 All；切換即時重新渲染，不重載頁面、不重新請求 API。以單選取代現有「只看執行中」按鈕，保留 Running 數量徽章。與 Project 篩選及文字搜尋取交集；Board 四個生命週期欄位維持不變，僅隱藏不符合的卡片。狀態輪詢更新後套用目前選擇，任務離開條件即消失。不得更動新增、編輯、刪除、執行、拖移、恢復、worktree 與後端狀態轉移。
判定：All 全部；Running = status ongoing；Completed = status closed 且無明確失敗結果；Failed = 已停止且有明確失敗證據（如 paused + run.phase 為 launch_failed / recovery_launch_failed），一般 paused 不算 Failed。未歸類的 new / paused 只在 All 顯示。若後端後續新增其他終止失敗 phase，先補契約測試再擴充白名單；不得以非空 error 字串或模糊比對認定 Failed。若 closed 的 final result 有明確失敗標記，Failed 優先於 Completed；現有 closed 由正常完成路徑產生，此延伸條件必須先查證欄位。
受影響專案 P1 為本 repo 的 ui/static 與 ui/tests；無 DB/API/schema 變更。主要風險是失敗定義混淆、背景刷新使選項重置、既有 Running Only 遺留事件造成交互衝突。驗收需在 Board/List、輪詢、CRUD/Run/Worktree 回歸中證明無副作用。

## Requirements
- R1：四選一篩選，初始 All，選中狀態可見且可鍵盤操作。
- R2：選項切換只更新 DOM，不重新載入頁面；搜尋、Project 篩選仍正常交集。
- R3：狀態分類按上述明確規則；Paused 普通暫停不算 Failed；未分類狀態僅 All。
- R4：Board/List 共用同一篩選；Running 徽章仍計算目前 Project/搜尋範圍內的 ongoing 數量，不隨狀態篩選變動。
- R5：刷新/輪詢時保留目前篩選，狀態改變立即反映於下一次既有資料刷新；無額外輪詢。
- R6：既有 Task CRUD、run/stop/resume/reset、拖移與 worktree 行為不變。
- R7：失敗載入時沿用既有錯誤提示；切換篩選不觸發額外 API；空結果保留既有空狀態。
## Acceptance Criteria
AC1 初始 All；AC2 四選一及 Board/List 立即同步；AC3 Paused 正常暫停不屬 Failed；AC4 啟動失敗的 Paused 屬 Failed；AC5 完成的 closed 屬 Completed；AC6 Project/搜尋/輪詢/CRUD/Run/Worktree regression PASS（實作階段執行）。
## 範圍與非目標
不新增狀態 enum、後端 endpoint、持久化欄位、URL query 或設定；篩選僅在目前頁面 session 保留，重新載入預設 All。保留原本生命週期看板四欄，不建立 Failed 第五欄。規劃階段不修改正式程式碼、不跑測試。
## 已確認決策
D1 Failed 必須已停止且有明確失敗證據；D2 單選取代 Running Only，保留 Running count。D3（設計推論）Failed 先以已查證 phase 白名單判定，避免將可恢復錯誤誤認終止；實作前應以測試固定其他終止失敗案例。
參見 [Architecture.md](Architecture.md)、[TestPlan.md](TestPlan.md)、[TODO.md](TODO.md)。
