## AI-generated SPEC 的強假設

AI-generated SPEC 並不是「給一個 Prompt，AI 就能知道所有事情」。

前提是：

**AI 必須取得足夠的 Evidence。**

### 可推導

如果流程關係可以從現有資料中找到，例如：

- Source Code
- DB / SQL
- API
- Scheduler
- MQ / Event
- Config
- Existing Test
- Documentation

AI 就可以自行推導 SPEC。

例如：

```text
DB STATUS = READY
    ↓
Scheduler
    ↓
Process
    ↓
STATUS = DONE
```

或：

```text
API
 ↓
Service
 ↓
DB STATUS Check
 ↓
Process
```

這類 Local Behavior 通常可以直接從程式推導。

---

### 不可推導

如果真正流程橫跨多個 Project，而且關係沒有存在任何可取得的 Evidence 中，例如：

```text
Project A
   ↓
Scheduler A
   ↓
其他系統處理
   ↓
Scheduler B
   ↓
Final Result
```

單看 Scheduler B，只能知道它會處理某個 DB Status，

但 AI 不一定知道：

**這筆資料其實必須先經過 Project A、Scheduler A 與其他系統。**

因此無法可靠產生完整 E2E SPEC。

---

### 解法

不需要人工重新撰寫完整 SPEC。

只要補充 AI 無法推導的最小必要資訊，例如：

```text
E2E Flow:

Project A
→ Scheduler A
→ Scheduler B

Scheduler A 的 Output
是 Scheduler B 的 Input。
```

也可以提供：

- Data Flow
- Architecture
- E2E Sample
- Existing SPEC
- Domain Material

再讓 AI 根據這些資訊繼續推導細節。

---

## 核心原則

> **能從 Evidence 找到的，交給 AI 推導；找不到的，只補最小必要 Context，而不是人工重寫完整 SPEC。**

簡化來說：

**Local Behavior → AI 自動推導**

**Cross-System Flow → 有 Evidence 就推導，沒有就補最小 Context**