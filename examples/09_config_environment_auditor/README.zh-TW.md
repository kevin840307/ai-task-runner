# 09 Config Environment Auditor — Clean Rerun

這是一個實務型 Mixed Validation 範例，重點是多格式設定檔分析、乾淨重跑，以及 deterministic black-box validation。

Python hard validator 只做 black-box 驗證，涵蓋：
- YAML / YML、JSON、INI / CFG、XML
- nested object 與 array
- 重複 XML sibling，使用 element-name index 判斷
- XML attribute
- missing / extra / changed / type mismatch
- 動態 environment 名稱
- malformed file 隔離
- unsupported file 計數
- 精確 file counter
- baseline 不存在時的行為
- deterministic byte-for-byte rerun

Mixed-formats fixture 的已驗證 totals：
- discovered = 12
- parsed = 9
- malformed = 1
- ignored = 2

Final AI validation：
- 3 個 Fresh、彼此獨立的 Validator Session
- 預設 majority vote
- 檢查 genericity、hardcode、fixture shortcut、over-design
- AI Validator 只在 Python hard validator PASS 後執行

這個 package 刻意不包含 implementation、Runner state、debug script 或之前的 AI artifact，確保每次測試都是 clean rerun。

執行：

    run_example.bat --backend qwen
