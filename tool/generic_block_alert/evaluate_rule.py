#!/usr/bin/env python3
import math

Z=2.5

def evaluate_rule(hist_exec,hist_fail,recent_exec,recent_fail):
    if recent_exec < 5:
        return "INSUFFICIENT"
    if hist_exec < 20:
        return "LEARNING"

    p=(hist_fail+1)/(hist_exec+2)
    expected=recent_exec*p
    variance=(
        recent_exec*p*(1-p)
        +(recent_exec**2)*p*(1-p)/hist_exec
    )
    min_extra=3 if recent_exec < 8 else 2
    threshold=max(min_extra,Z*math.sqrt(max(variance,1e-12)))

    main=(recent_fail-expected)>=threshold
    expected_success=recent_exec*(1-p)
    actual_success=recent_exec-recent_fail
    collapse=(p<=0.90 and expected_success>=4 and actual_success==0)

    return "ALERT" if (main or collapse) else "OK"

if __name__=="__main__":
    examples=[
        ("1% normal",1000,10,100,1),
        ("1% -> 20%",1000,10,100,20),
        ("90% normal",1000,900,100,91),
        ("90% -> 100%",1000,900,100,100),
        ("sparse 10% -> 4/8",20,2,8,4),
        ("sparse 90% -> 8/8",20,18,8,8),
    ]
    for name,*args in examples:
        print(name,evaluate_rule(*args))
