#!/usr/bin/env python3
"""
Generic block failure anomaly simulation.

Requires:
    pip install numpy pandas

The rule intentionally avoids fixed failure-rate thresholds because some blocks
may normally fail 90% of the time. It compares recent failures against each
block's own historical failure probability.

Run:
    python simulate_alert.py
"""
import math
import numpy as np
import pandas as pd

Z = 3.1
MIN_HISTORY = 10
MIN_RECENT = 5
TRIALS = 30000
SEED = 20261026

def evaluate_rule(hist_exec, hist_fail, recent_exec, recent_fail):
    if recent_exec < MIN_RECENT:
        return "INSUFFICIENT", {"reason": "too_few_recent_samples"}
    if hist_exec < MIN_HISTORY:
        return "LEARNING", {"reason": "too_few_history_samples"}

    # Laplace smoothing prevents exact 0% / 100% baseline from tiny history.
    p = (hist_fail + 1.0) / (hist_exec + 2.0)

    expected_fail = recent_exec * p

    # Natural recent variance + uncertainty of estimated historical baseline.
    variance = (
        recent_exec * p * (1.0 - p)
        + (recent_exec ** 2) * p * (1.0 - p) / hist_exec
    )

    min_extra = 4.0 if recent_exec < 20 else 3.0
    allowance = max(min_extra, Z * math.sqrt(max(variance, 1e-12)))
    excess_fail = recent_fail - expected_fail

    # Protect high-baseline cases, e.g. normal failure ~= 90%.
    expected_success = recent_exec * (1.0 - p)
    actual_success = recent_exec - recent_fail
    success_collapse = expected_success >= 8.0 and actual_success <= 1

    alert = (excess_fail >= allowance) or success_collapse

    return ("ALERT" if alert else "OK"), {
        "normal_failure_ratio": p,
        "expected_fail": expected_fail,
        "actual_fail": recent_fail,
        "excess_fail": excess_fail,
        "allowance": allowance,
        "expected_success": expected_success,
        "actual_success": actual_success,
        "success_collapse": success_collapse,
    }

SCENARIOS = [
    ("A", "low baseline / normal",              1000, 10,  100,   1, "OK"),
    ("B", "low baseline / degraded",            1000, 10,  100,  20, "ALERT"),
    ("C", "90% baseline / still normal",         1000, 900, 100,  91, "OK"),
    ("D", "90% baseline / success collapsed",    1000, 900, 100, 100, "ALERT"),
    ("E", "sparse / 90% baseline / 5 of 5 fail", 100,  90,    5,   5, "OK"),
    ("F", "sparse / 10% baseline / 5 of 5 fail", 100,  10,    5,   5, "ALERT"),
    ("G", "20% baseline / normal",                200,  40,   20,   4, "OK"),
    ("H", "20% baseline / degraded",              200,  40,   20,  12, "ALERT"),
    ("I", "new block / no history",                 0,   0,  100,  80, "LEARNING"),
    ("J", "3-4 day cadence / only 3 recent",       20,   2,    3,   2, "INSUFFICIENT"),
]

def run_deterministic():
    print("=== deterministic scenarios ===")
    passed = 0
    for sid, name, he, hf, re, rf, expected in SCENARIOS:
        actual, detail = evaluate_rule(he, hf, re, rf)
        ok = actual == expected
        passed += int(ok)
        print(f"{sid}: {name:42s} expected={expected:12s} actual={actual:12s} pass={ok}")
    print(f"PASS {passed}/{len(SCENARIOS)}")

def monte_carlo_rate(rng, p0, p1, recent_n, hist_n):
    hist_f = rng.binomial(hist_n, p0, size=TRIALS)
    recent_f = rng.binomial(recent_n, p1, size=TRIALS)

    p = (hist_f + 1.0) / (hist_n + 2.0)
    expected_fail = recent_n * p
    variance = (
        recent_n * p * (1.0 - p)
        + (recent_n ** 2) * p * (1.0 - p) / hist_n
    )
    min_extra = 4.0 if recent_n < 20 else 3.0
    allowance = np.maximum(min_extra, Z * np.sqrt(np.maximum(variance, 1e-12)))
    excess = recent_f - expected_fail

    expected_success = recent_n * (1.0 - p)
    actual_success = recent_n - recent_f
    success_collapse = (expected_success >= 8.0) & (actual_success <= 1)

    return float(np.mean((excess >= allowance) | success_collapse))

def run_monte_carlo():
    rng = np.random.default_rng(SEED)
    normal_ps = [0.001, 0.01, 0.05, 0.10, 0.30, 0.50, 0.90]
    recent_ns = [5, 10, 20, 50, 100, 500]
    rows = []

    for p0 in normal_ps:
        for n in recent_ns:
            hist_n = max(200, n * 5)
            rows.append({
                "type": "normal_false_positive",
                "baseline_p": p0,
                "current_p": p0,
                "recent_n": n,
                "history_n": hist_n,
                "alert_rate": monte_carlo_rate(rng, p0, p0, n, hist_n),
            })

    degradations = [
        (0.01, 0.10), (0.01, 0.20), (0.05, 0.20), (0.10, 0.30),
        (0.30, 0.60), (0.50, 0.80), (0.90, 0.97), (0.90, 1.00),
    ]
    for p0, p1 in degradations:
        for n in recent_ns:
            hist_n = max(200, n * 5)
            rows.append({
                "type": "degradation_detection",
                "baseline_p": p0,
                "current_p": p1,
                "recent_n": n,
                "history_n": hist_n,
                "alert_rate": monte_carlo_rate(rng, p0, p1, n, hist_n),
            })

    df = pd.DataFrame(rows)
    normal = df[df.type == "normal_false_positive"]
    print("\n=== Monte Carlo summary ===")
    print(f"max false-positive rate:    {normal.alert_rate.max():.4%}")
    print(f"median false-positive rate: {normal.alert_rate.median():.4%}")
    print("\nFull result:")
    print(df.to_string(index=False))

if __name__ == "__main__":
    run_deterministic()
    run_monte_carlo()
