#!/usr/bin/env python3
"""
Re-run the exhaustive v11 alert simulation.

Requirements:
    pip install numpy pandas

Outputs:
    exhaustive_grid_results.csv
    absolute_change_results.csv
    summary_by_severity.csv
    summary_by_recent_samples.csv
    summary_by_history_samples.csv
"""
import numpy as np
import pandas as pd
import itertools

SEED=20261026
TRIALS=3000
Z=2.5
MIN_RECENT=5
MIN_HISTORY=20

def min_excess_for_n(n):
    return 3 if n < 8 else 2

def odds_shift(p,m):
    odds=p/(1-p)
    o2=odds*m
    return o2/(1+o2)

baseline_ps=[0.001,0.005,0.01,0.05,0.10,0.30,0.50,0.70,0.90,0.95]
recent_ns=[5,8,10,20,50,100,200,500,1000,10000]
history_ns=[20,50,100,500,2000]
severities=[
    ("normal",1.0),
    ("slight_odds_x1.5",1.5),
    ("moderate_odds_x3",3.0),
    ("severe_odds_x10",10.0),
    ("extreme_odds_x50",50.0),
]

rng=np.random.default_rng(SEED)
rows=[]
for p0,n,h in itertools.product(baseline_ps,recent_ns,history_ns):
    hf=rng.binomial(h,p0,size=TRIALS)
    ph=(hf+1)/(h+2)
    expected=n*ph
    var=n*ph*(1-ph)+(n**2)*ph*(1-ph)/h
    allowance=np.maximum(min_excess_for_n(n),Z*np.sqrt(np.maximum(var,1e-12)))
    expected_success=n*(1-ph)

    for label,m in severities:
        p1=odds_shift(p0,m)
        rf=rng.binomial(n,p1,size=TRIALS)
        main=(rf-expected)>=allowance
        collapse=(ph<=0.90)&(expected_success>=4)&((n-rf)==0)
        ar=float(np.mean(main|collapse))
        rows.append([label,p0,p1,n,h,h/n,ar])

    rf=np.full(TRIALS,n)
    main=(rf-expected)>=allowance
    collapse=(ph<=0.90)&(expected_success>=4)
    rows.append(["all_fail",p0,1.0,n,h,h/n,float(np.mean(main|collapse))])

df=pd.DataFrame(rows,columns=[
    "severity","baseline_failure_rate","current_failure_rate",
    "recent_exec","history_exec","history_to_recent_ratio","alert_rate"
])
df.to_csv("exhaustive_grid_results.csv",index=False)

df.groupby("severity").alert_rate.agg(["mean","median","max","min"]).to_csv(
    "summary_by_severity.csv"
)
df.groupby(["severity","recent_exec"]).alert_rate.mean().to_csv(
    "summary_by_recent_samples.csv"
)
df.groupby(["severity","history_exec"]).alert_rate.mean().to_csv(
    "summary_by_history_samples.csv"
)

print(df.groupby("severity").alert_rate.agg(["mean","median","max","min"]))
