{% include "stages/execution.md" %}

只修正 Stage 2 Grill / Review / Python Gate 的具體 finding。以已驗證 Flow/Branch/Outcome 為 source of truth；補足真實缺漏的 coverage，刪除 unsupported/duplicate/non-E2E Case。不要為了達 90% 硬造 Case；若 branch/outcome 本身錯誤，回報前一 Stage 問題，不要偷改 flows.yaml。
