# Simulation Summary

Seed: `20261026`  
Monte Carlo trials per cell: `30,000`

## Deterministic scenarios

| scenario   | name                             | expected     | actual       | pass   | note                                                                |
|:-----------|:---------------------------------|:-------------|:-------------|:-------|:--------------------------------------------------------------------|
| A          | 低失敗率、目前正常               | OK           | OK           | True   | 平常約 1%，現在約 1%，不應告警。                                    |
| B          | 低失敗率、突然惡化               | ALERT        | ALERT        | True   | 平常約 1%，現在 20%，應告警。                                       |
| C          | 平常失敗率 90%，目前仍接近平常   | OK           | OK           | True   | 90% 本來就是正常，不應因絕對失敗率高而誤報。                        |
| D          | 平常失敗率 90%，成功能力幾乎歸零 | ALERT        | ALERT        | True   | 歷史預期約 10 次成功，但實際 0 次，應抓到。                         |
| E          | 極低樣本且平常失敗率很高         | OK           | OK           | True   | 5/5 failure 對平常 90% failure 的 block 並不夠異常。                |
| F          | 極低樣本但相對歷史非常異常       | ALERT        | ALERT        | True   | 平常約 10%，5/5 failure 已遠超正常波動。                            |
| G          | 中等失敗率、目前正常             | OK           | OK           | True   | 平常約 20%，目前也是 20%。                                          |
| H          | 中等失敗率、明顯惡化             | ALERT        | ALERT        | True   | 平常約 20%，目前 60%。                                              |
| I          | 新積木、尚無歷史                 | LEARNING     | LEARNING     | True   | 沒有 baseline 時無法通用地判斷 80% 是正常或異常；先學習，避免誤報。 |
| J          | 3~4 天才一筆，近期資料仍太少     | INSUFFICIENT | INSUFFICIENT | True   | 近期只有 3 筆，不強行判斷；擴大到 30d 直到至少 5 筆。               |

Result: **10/10 passed**

## False-positive simulation

Each row means the current failure probability is exactly the same as the historical normal probability.

Values are alert percentages.

|   baseline_p |     5 |    10 |    20 |    50 |   100 |   500 |
|-------------:|------:|------:|------:|------:|------:|------:|
|        0.001 | 0     | 0     | 0     | 0     | 0     | 0.133 |
|        0.01  | 0     | 0     | 0.007 | 0.14  | 0.583 | 0.453 |
|        0.05  | 0     | 0.007 | 0.653 | 0.633 | 0.483 | 0.253 |
|        0.1   | 0.003 | 0.1   | 0.53  | 0.433 | 0.39  | 0.14  |
|        0.3   | 0     | 0.2   | 0.163 | 0.14  | 0.163 | 0.113 |
|        0.5   | 0     | 0.067 | 0.097 | 0.1   | 0.093 | 0.097 |
|        0.9   | 0     | 0     | 0     | 0.003 | 0.02  | 0.053 |

Summary:

- Max false-positive rate in this grid: **0.653%**
- Median false-positive rate: **0.095%**
- Mean false-positive rate: **0.149%**

The highest cells are mostly small/discrete sample combinations. This is why the design does not alert with fewer than 5 recent executions.

## Degradation detection simulation

Values are detection percentages.

|             |   5 |   10 |   20 |   50 |   100 |   500 |
|:------------|----:|-----:|-----:|-----:|------:|------:|
| (0.01, 0.1) | 0   |  0.2 | 13.6 | 69.4 |  95.7 | 100   |
| (0.01, 0.2) | 0   |  3.2 | 59.1 | 99   | 100   | 100   |
| (0.05, 0.2) | 0   |  3.5 | 40.7 | 72.7 |  96   | 100   |
| (0.1, 0.3)  | 0.2 |  9.7 | 40.2 | 75.7 |  97.6 | 100   |
| (0.3, 0.6)  | 0   | 16.4 | 39.6 | 84.6 |  99.6 | 100   |
| (0.5, 0.8)  | 0   |  5.2 | 27.1 | 82.5 |  99.7 | 100   |
| (0.9, 0.97) | 0   |  0   |  0   |  0.1 |  18.6 |  99.6 |
| (0.9, 1.0)  | 0   |  0   |  0   |  0.2 |  94.8 | 100   |

For representative strong degradations with `recent_n >= 100` (excluding the subtle `90% -> 97%` case):

- Mean recall: **98.8%**
- Minimum recall: **94.8%**

High-normal-failure check:

- Normal `90% -> 91%`, `n=100`: alert rate **0.120%**
- Degradation `90% -> 100%`, `n=100`: detection **94.5%**

## Important limitation

No generic rule can reliably tell whether a brand-new block with no history and only one execution (`1/1 failed`) is abnormal when some valid blocks normally fail around 90%.

Therefore this design intentionally returns **LEARNING** until there is enough historical evidence. For very sparse blocks (for example one execution every 3–4 days), use a 30-day recent window and a longer historical window. Detection will necessarily be slower because there is less statistical evidence.
