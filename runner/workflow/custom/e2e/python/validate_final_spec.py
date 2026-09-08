#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from e2e_validation_common import load_yaml, evidence_map, validate_flows, validate_cases, validate_final, case_coverage, write_report


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root', required=True); args=ap.parse_args()
    root=Path(args.project_root).resolve(); out=root/'result'/'e2e_spec'
    errors=[]; warnings=[]; metrics={}
    try:
        evidences,verified,total=evidence_map(root,load_yaml(out/'evidence_index.yaml'),errors,warnings)
        flows=validate_flows(load_yaml(out/'flows.yaml'),evidences,errors,warnings)
        cases=validate_cases(load_yaml(out/'cases.yaml'),flows,evidences,errors,warnings)
        validate_final(load_yaml(out/'e2e_spec.yaml'),flows,cases,evidences,errors,warnings)
        cov=case_coverage(flows,cases)
        ratio=(verified/total if total else 0.0)
        if total and ratio < 1.0: errors.append(f'all declared evidence must remain verified; got {ratio:.3f}')
        if cov['critical_branch_coverage_ratio'] < 1.0: errors.append('final critical branch coverage must be 100%')
        if cov['critical_outcome_coverage_ratio'] < 1.0: errors.append('final critical outcome coverage must be 100%')
        if cov['branch_coverage_ratio'] < 0.90: errors.append('final business branch coverage must be >= 90%')
        if cov['outcome_coverage_ratio'] < 0.90: errors.append('final outcome coverage must be >= 90%')
        metrics={'evidence_total':total,'evidence_verified':verified,'evidence_verified_ratio':ratio,'flows':len(flows),'cases':len(cases),**cov}
    except Exception as exc: errors.append(str(exc))
    write_report(root,'final',errors,warnings,metrics)
    print('E2E_SPEC_FINAL_PASS' if not errors else 'E2E_SPEC_FINAL_FAIL')
    for e in errors[:40]: print(f'- {e}')
    if not errors: print(json.dumps(metrics,ensure_ascii=False))
    return 1 if errors else 0

if __name__=='__main__': raise SystemExit(main())
