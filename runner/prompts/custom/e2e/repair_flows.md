{% include "stages/execution.md" %}

只修正目前 Stage 1 Grill / Review / Python Gate 的具體 finding。讀 `source_inventory.yaml`、`flows.yaml`、`evidence_index.yaml` 與 finding 指向的最小 source。

優先修：inventory accounting、假的/距離過遠 evidence、漏 branch/outcome、錯誤 intermediate/final state、漏 SQL/parameter 影響。保留已驗證內容，不重做整份文件；禁止降低 Gate、捏造 evidence 或用 exclusion 掩蓋沒探索的 project/entrypoint。


Scanner safety：
- explicit evidence path/symbol/keyword 錯誤時，必須修成真實 evidence；不可降級 Gate。
- 若 finding 只是「inventory 沒掃到」，先查 source。source 有 direct evidence 時用 additional_entrypoint/project 或 evidence_refs 修正，不得刪掉真實 Flow。
- `scanner_limitations` / `dynamic_candidates` 要優先追查 legacy/reflection/dynamic behavior。
