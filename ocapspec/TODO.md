## 實作 TODO（全部未開始）
- [ ] T1 [P1; R1–R6; F1–F5] 定位 Tasks HTML 與舊 Running Only 測試；確認 failure phase 終止語義與既有 UI 呼叫點。證據：路徑/契約盤點。
- [ ] T2 [P1; 依賴 T1; R3; F1; U1] 建立明確終止失敗白名單與分類測試，不以一般 paused/error 推斷 Failed。證據：U1。
- [ ] T3 [P1; 依賴 T2; R1–R5; F1,F2,F3; E1,E2; I1,U2,U3] 實作四選一、共用 visibleTasks、保留 Running 徽章與 refresh 行為。證據：E1/E2/I1/U2/U3。
- [ ] T4 [P1; 依賴 T3; R1,R4; F3,F5; E1] 驗證 Board/List、鍵盤/焦點、窄螢幕、既有 UI parity。證據：瀏覽器斷言與截圖。
- [ ] T5 [P1; 依賴 T3; R6; F4; E3,E4; I2] 補齊 CRUD、Run、Stop、Resume、Reset、drag/drop、worktree regression。證據：E3/E4/I2。
- [ ] T6 [P1; 依賴 T4,T5; R1–R6; F1–F5; E1–E5; I1,I2; U1–U3] 執行 UI、Task service、Runner/worktree 相關既有測試；保存實際命令、結果與失敗紀錄。證據：測試輸出；不得未執行先勾。
- [ ] T7 [P1; 依賴 T6; R1–R6; F1–F5] 核對 git diff 與 Spec/Architecture，確保無 API、schema、Runner 或非相關重構。證據：diff review。
- [ ] T8 [P1; 依賴 T7; R1–R6; E1–E5] 獨立 Review gate：檢查分類、競態、焦點、既有操作 regression；只有有證據才標完成。證據：review 記錄。
## 規劃邊界
本文件為規劃，不執行程式碼修改、測試、commit 或 push。四份文件需保持需求→檔案→測試→TODO 可追溯。
