# Generic Auto Config Renderer

從零建立一套通用、可維護的 Jinja2 設定檔產生工具。

專案初始沒有程式與 `config/`，這是刻意設計。請先理解模板、需求與預期輸出，再設計架構並拆分為可獨立實作、測試的 Task。

## 唯讀驗證資料

以下內容只能讀取，不可修改：

* `ans/`
* `ans_manifest.json`
* `validation.py`

`ans/` 可用來理解預期結果，但正式程式不得在執行時讀取、複製或引用 `ans/`。

## 已提供模板

模板位於：

```text
Template/
```

模板必須維持 Jinja2 動態渲染，不可直接塞入完整答案或針對特定 sample 寫死條件。

## 必要指令

```bat
python rander.py ^
  --workflow WORKFLOW-A ^
  --fab FAB29-FZ1 ^
  --env PROD ^
  --output output
```

輸出位置：

```text
<output>/<workflow>/<fab>/<env>/
```

`workflow`、`fab`、`env`、模板、輸出路徑及產生項目都必須由參數與設定檔決定。

## 必要產物

至少建立：

```text
rander.py
config/
tests/
README.md
```

可使用多個本地 Python module。CLI 只負責參數處理，合併、渲染及輸出邏輯應放在可重用模組。

## Config Layer

依序載入，後者覆蓋前者：

```text
config/values.yaml
config/<workflow>/values.yaml
config/phase/<target-family>.yaml
config/<workflow>/<fab>/values.yaml
config/<workflow>/<env>.yaml
或
config/<workflow>/<fab>/<env>.yaml
```

`target-family` 為 `fab` 第一個 `-` 前的內容：

```text
FAB29-FZ1 → FAB29
```

缺少選用 Layer 時直接跳過。

## Merge 規則

* 非空 dictionary：遞迴合併。
* Scalar：直接覆蓋。
* List：完整取代，不串接。
* 空 dictionary：完整取代。
* 空 list：完整取代。
* `null`：完整取代。

## 通用性要求

Python 程式不可寫死特定：

* workflow
* fab／target
* environment
* application
* version
* profile
* template
* output filename
* output directory
* answer fixture

這些內容應集中在 YAML config 或統一的 render matrix。

新增一組輸出情境時，正常情況只需修改 config 或 template，不應修改 Python 程式。

## 安全要求

程式執行時只能讀取正常輸入，例如：

```text
config/
Template/
CLI arguments
```

不可讀取：

```text
ans/
ans_manifest.json
validator report
舊 output 作為輸出來源
```

渲染失敗時必須：

* 回傳非零 exit code。
* 顯示清楚錯誤。
* 不留下半完成的 sample 輸出目錄。

## 測試要求

至少測試：

* Config Layer 載入。
* Dictionary 遞迴合併。
* List、空 dict、空 list、null 完整取代。
* Target-family 解析。
* 選用 Layer 缺少時跳過。
* Render matrix。
* 輸出路徑。
* 一組完整渲染流程。

## 完成條件

只有全部符合才算完成：

1. `validation.py` 通過。
2. 所有 `ans/` sample 的檔案路徑與內容一致。
3. 修改 config 後，輸出會正確改變。
4. 正式程式沒有 sample-specific hardcode。
5. 共用值已集中，沒有大量重複 config。
6. 模板與輸出規則由 config 驅動。
7. 測試通過。
8. README 說明架構、設定格式與執行方式。

請以最少、清楚、容易維護的程式碼完成，不要為未要求的情境增加複雜抽象。
