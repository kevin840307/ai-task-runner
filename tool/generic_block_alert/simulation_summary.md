# Simulation Summary — v11

Seed: `20261026`  
Trials per grid cell: `3,000`

## Coverage

Baseline failure rate:
`0.1%, 0.5%, 1%, 5%, 10%, 30%, 50%, 70%, 90%, 95%`

Recent executions:
`5, 8, 10, 20, 50, 100, 200, 500, 1000, 10000`

History executions:
`20, 50, 100, 500, 2000`

Severity:
- Normal
- Slight: failure odds x1.5
- Moderate: failure odds x3
- Severe: failure odds x10
- Extreme: failure odds x50
- All fail

Additional absolute changes:
`+2pp, +5pp, +10pp, +20pp`

## Deterministic scenarios

**14/14 PASS**

## False positive

Across all normal combinations:

- Mean: **0.456%**
- Median: **0.233%**
- Worst tested cell: **2.967%**

When history executions >= 3x recent executions:

- Mean: **0.438%**

## Overall alert rate by severity

| severity         | mean_alert_rate   | median_alert_rate   | max_alert_rate   | min_alert_rate   |
|:-----------------|:------------------|:--------------------|:-----------------|:-----------------|
| all_fail         | 82.61%            | 100.0%              | 100.0%           | 0.0%             |
| extreme_odds_x50 | 68.51%            | 98.88%              | 100.0%           | 0.0%             |
| moderate_odds_x3 | 29.1%             | 9.53%               | 100.0%           | 0.0%             |
| normal           | 0.46%             | 0.23%               | 2.97%            | 0.0%             |
| severe_odds_x10  | 51.87%            | 55.7%               | 100.0%           | 0.0%             |
| slight_odds_x1.5 | 9.23%             | 1.57%               | 100.0%           | 0.0%             |

## Detection by recent sample size

|   recent_exec |   all_fail |   extreme_odds_x50 |   moderate_odds_x3 |   normal |   severe_odds_x10 |   slight_odds_x1.5 |
|--------------:|-----------:|-------------------:|-------------------:|---------:|------------------:|-------------------:|
|             5 |       59.7 |               22.3 |                0.9 |      0.1 |               6.2 |                0.2 |
|             8 |       68.2 |               43.8 |                5.7 |      0.4 |              24.1 |                1.3 |
|            10 |       70.3 |               49.2 |                7.1 |      0.4 |              28.8 |                1.3 |
|            20 |       80   |               65.4 |               13.7 |      0.5 |              43.5 |                2.1 |
|            50 |       86.3 |               76.6 |               27.9 |      0.6 |              58.5 |                4   |
|           100 |       88.3 |               80.9 |               36.4 |      0.5 |              63.8 |                6.5 |
|           200 |       92.5 |               86   |               43.1 |      0.5 |              69.8 |               10.7 |
|           500 |       93.2 |               86.8 |               49.6 |      0.5 |              73.6 |               17.4 |
|          1000 |       93.7 |               86.9 |               52.1 |      0.5 |              74.5 |               21.6 |
|         10000 |       93.7 |               87.1 |               54.3 |      0.4 |              75.6 |               27   |

Interpretation:

- Slight anomalies are intentionally mostly ignored; otherwise false alert rises sharply.
- Moderate anomalies need more observations.
- Severe/extreme anomalies are increasingly caught as recent sample count grows.
- Sparse 5~10-sample windows are deliberately conservative.
- `all_fail` does not always mean anomaly when the block normally fails 90~95%.

## Sparse 3~4 day cadence

If a block runs once every 3~4 days:

- 30d recent ≈ 7~10 executions
- 90d history ≈ 22~30 executions

The deterministic sparse cases now pass after tuning:
- normal ~10%, recent 4/8 fail => Alert
- normal ~90%, recent 8/8 fail => OK

This illustrates why self-baseline is needed.

## Final selected rule

```text
recent < 5      => INSUFFICIENT
history < 20    => LEARNING

p = (history_fail + 1) / (history_exec + 2)

expected_fail = recent_exec * p

variance =
  recent_exec * p * (1-p)
  + recent_exec^2 * p * (1-p) / history_exec

minimum unexpected failures:
  recent 5~7  => 3
  recent >=8  => 2

threshold =
  max(minimum unexpected failures, 2.5 * sqrt(variance))

Alert when:
  recent_fail - expected_fail >= threshold
```

Extra high-normal-failure protection:

```text
normal failure <= 90%
AND expected successes >= 4
AND actual successes = 0
=> Alert
```

This is intentionally disabled above a 90% normal failure baseline to avoid false alerts for 95%-normal blocks.
