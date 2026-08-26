# Regression Test Framework 演進

## Stage 1：降低 Regression Test 重工

Regression Test 很耗時，但不可或缺。但目前每個專案都需要重新建立 Regression Test 與 Mock 機制，容易造成大量重工。

因此建立 Regression Test Framework，希望把共通能力抽出來。

目標是：

**任何專案只要提供一個 E2E Sample，再透過 Skill 讓 AI 延伸產生其他 Test Case。**

目前使用 6 個 Skills 完成這項任務。

---

## Stage 1 的問題：AI 不夠穩定

即使有 **Regression Test Framework + AI**，實際使用仍有幾個問題：

1. 小模型如何產生正確的 Test Case
2. 如何穩定執行長時間任務
3. 如何降低人工介入

例如：

- API 異常需要等待
- Agent 異常導致流程中斷
- 任務常需要多輪對話才能完成

小模型很難一次做到位。

所以可以把問題變成：

**既然不能一次完成，能不能讓 AI 持續執行、驗證、修正，直到符合要求？**

### 方案 1：修改 Agent Source Code

直接修改 Agent 本身可以控制行為，但需要考慮：

- 社群版本持續更新
- 相容性問題
- 後續維護成本

### 方案 2：使用 Agent 內建 Loop

例如 `/goal`、`/ralph-loop` 等機制。

這些方法確實有幫助，但如果希望長時間穩定執行，且結果持續接近預期，仍有一定難度。

### 方案 3：Workflow Loop

相比直接修改 Agent Source Code，或依賴 `/goal`、`/ralph-loop` 等 Agent 內建機制，我們選擇在 Agent 外層建立 Workflow Controller。

核心概念：

**Agent 負責執行，Workflow 負責控制。**

Workflow 統一負責：

- Retry / Recovery
- Session 管理
- 異常監控
- 檔案 / Git 保護
- 驗證與修正

因此底層可以替換 Qwen、OpenCode、Codex 等不同 Agent。

目標不是讓 Agent 永遠不出錯，而是讓 Regression Test 生成具備：

**長時間、低人工介入、可恢復的執行能力。**

---

# Stage 2：從產生 Test Case 轉向驗證結果

Stage 1 解決了：

**AI 怎麼持續工作。**

但還有另一個更根本的問題：

**AI 到底應該產生哪些 Regression Test？**

傳統做法：

**產生 Regression Test → 執行 → 驗證**

但要完整列出所有 Regression Test，本身就非常困難。

這就像數學遇到原問題難以直接求解時，會把問題轉換成另一個更容易處理的形式。

因此我們把問題從：

**「AI 應該產生哪些 Test Case？」**

轉成：

**「在明確的約束條件與驗證規則下，讓 AI 自己找到符合要求的 Test Case。」**

不再限制 AI 一定怎麼實作。

我們只定義：

**Prepare → Main() → Verify**

### Example 1

```text
Prepare
Insert SQL

Main
Run EXE

Verify
1. Regression Framework 驗證結果
   - DB 是否有預期紀錄
   - 是否產生特定 Log(Option)

2. 驗證 Test Case 可信度
   - 不允許偷塞驗證資料
   - 不允許繞過真正流程

3. Code Coverage Rate 符合要求
```

### Example 2

```text
Prepare
Insert SQL

Main
Trigger API

Verify
1. Regression Framework 驗證結果
   - DB 是否有預期紀錄
   - 是否產生特定 Log(Option)

2. 驗證 Test Case 可信度
   - 不允許偷塞驗證資料
   - 不允許繞過真正流程

3. Code Coverage Rate 符合要求
```

這有點像深度學習的黑盒概念：

**我們真正關心的是輸出結果，中間如何找到答案不是重點。**

核心概念：

**與其窮舉 Test Case，不如先定義驗證方法，讓 AI 自己找到能通過驗證的實作方式。**

---

# 最終 Regression Test 架構

整體可以收斂成：

```text
E2E Sample
    ↓
定義驗證條件
    ↓
AI Generate With Skills
    ↓
Run
    ↓
Verify
    ↓
FAIL → Repair → Retry
    ↓
PASS
```

也就是：

**Regression Framework 定義「什麼叫正確」，AI 負責找到「怎麼做到正確」。**

---

# 延伸應用

雖然這套 Workflow 是從 Regression Test 發展出來，但其核心能力也可以延伸到其他「結果可驗證」的任務。

## Unit Test

**推薦程度：★★★★★**

輸入、輸出、Exception、Boundary、Coverage 都可以明確驗證，因此非常適合。

## PRR Report

**推薦程度：★★★★★**

給定一份人寫的PRR(只需提供一次), 只要能定義格式、必要內容與品質規則，就可以：

**Generate → Validate → Repair**

## Security Report

**推薦程度：★★★★☆**

可透過：

**Multi-Agent → Validate / Score → 去重 → 聯集 → Report**

提高穩定度，但 Security 本身仍存在較多主觀判斷，因此較適合作為輔助。

---

# 核心

整套設計最終仍然服務於 Regression Test：

**從「替每個專案寫大量 Test Case」，逐步演進成「定義驗證條件，讓 AI 自動生成、執行、修正 Regression Test」。**

而它之所以能延伸到其他場景，是因為背後真正抽象出的能力是：

**只要結果可以被明確驗證，就可以交給 Workflow 持續生成、驗證與修正。**