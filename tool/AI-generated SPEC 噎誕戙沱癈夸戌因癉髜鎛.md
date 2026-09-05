**AI-generated SPEC → SPEC-driven Generation → Evaluation-driven Iteration**

也就是三層責任：

1. **AI 依照現有資料自動產生 SPEC**
2. **AI 依 SPEC 產生 Regression Test**
3. **我們主要定義 Evaluation / Verification，讓 AI 根據 Feedback 自行修正**

但這裡有一個很重要的前提：

## AI-generated SPEC 是建立在「強假設」之上

這並不代表：

**任何任務只要給 AI 一個簡單 Prompt，就可以自動產生正確 SPEC。**

AI 能夠自動產生 SPEC，是因為我們假設目前的問題空間具備足夠的可推導資訊。

例如 AI 可以取得：

- 現有 Source Code
- Project Documentation
- Existing E2E Sample
- API / DB / Log / Message 定義
- Regression Framework DSL
- Existing Test Case
- 執行結果與錯誤資訊
- Domain Material
- 前一階段產出的 Project Discovery / Documentation

也就是說：

**AI 不是憑空產生 SPEC，而是從現有系統留下的 Evidence 中推導 SPEC。**

這個差異非常重要。

---

### 強假設 1：系統中存在足夠的 Evidence

如果 Source Code、文件、Sample、Log、DB Schema 等資訊，本身就無法反映真正的 Business Requirement，那 AI 也不可能憑空知道正確答案。

例如：

```text
程式碼行為：A → B → C
```

AI 可以推導：

```text
可能需要驗證 A → B → C 的流程
```

但如果真正的需求其實是：

```text
未來應該改成 A → D → C
```

而這件事情只存在某個人的腦中，

那 AI 無法從現有 Evidence 推導出這個需求。

因此：

**AI-generated SPEC 比較適合「從既有系統推導應有行為」，而不是憑空創造不存在的需求。**

---

### 強假設 2：目標結果必須可以被驗證

即使 AI 能產生很多 SPEC，如果我們無法判斷結果是否正確，整個 Feedback Loop 就無法收斂。

因此最好存在某種可驗證訊號，例如：

- DB 是否產生預期資料
- 是否產生特定 Log
- API Response 是否符合條件
- Coverage 是否達標
- Regression Framework 是否 PASS
- AI Review 是否符合明確 Criteria
- Python Validator 是否通過

換句話說：

**不是所有問題都適合這套架構。**

這套方式特別適合：

**結果比過程更容易驗證的問題。**

---

### 強假設 3：問題空間必須存在合理邊界

如果任務完全開放，例如：

> 「幫我設計世界上最好的系統。」

這種問題沒有明確邊界，也沒有唯一可接受的 Evaluation。

AI 很難知道什麼時候應該停止。

但 Regression Test 不一樣。

我們通常可以限制：

```text
Target Project
Target Flow
Target Function
Target Coverage
Expected DB Result
Expected Log
Allowed / Forbidden Behavior
```

因此搜尋空間可以被控制。

---

### 強假設 4：SPEC 可以從 Evidence 推導，而不是完全依賴未知 Requirement

這也是為什麼前面需要：

**Project Discovery → Project Documentation → E2E SPEC**

Discovery 與 Documentation 並不是多餘步驟。

它們是在逐步把：

**隱藏在程式碼與系統裡的資訊**

轉成：

**AI 可以理解與推導的 Context。**

因此整個流程比較像：

```text
Raw Project
   ↓
Evidence Extraction
   ↓
Project Understanding
   ↓
AI-generated SPEC
   ↓
Regression Test Generation
```

而不是：

```text
一個 Prompt
   ↓
神奇地產生正確 SPEC
```

---

## 所以真正的假設是

我們不是假設：

> **AI 足夠聰明，所以任何事情都能自己做。**

而是：

> **當問題具有足夠 Evidence、合理邊界，而且結果可以被驗證時，AI 可以從 Evidence 推導候選 SPEC，再透過 Evaluation 不斷修正結果。**

這也是整個方法能成立的基礎。

---

甚至可以換一個比較直覺的比喻。

這就像請一個工程師接手既有系統。

我們不會只跟他說：

> 「幫我把 Regression Test 全部補好。」

然後什麼都不給他。

至少還是會讓他看：

- Source Code
- Existing Test
- System Document
- Log
- DB
- Sample
- Requirement

AI 也是一樣。

**自動化並不代表沒有輸入，而是把原本需要人工閱讀、理解與整理 Evidence 的過程，也交給 AI。**

---

因此 **AI-generated SPEC** 更精準的理解應該是：

> **Evidence-grounded AI-generated SPEC**

也就是：

**AI 根據既有 Evidence 推導 SPEC，而不是憑空發明 SPEC。**