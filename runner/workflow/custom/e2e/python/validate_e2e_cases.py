#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from e2e_validation_common import load_yaml, evidence_map, validate_flows, validate_cases, case_coverage, validate_case_inventory_refs, write_report, text


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root', required=True); args=ap.parse_args()
    root=Path(args.project_root).resolve(); out=root/'result'/'e2e_spec'
    errors=[]; warnings=[]; metrics={}
    try:
        inventory=load_yaml(out/'source_inventory.yaml')
        evidences,verified,total=evidence_map(root,load_yaml(out/'evidence_index.yaml'),errors,warnings)
        flows=validate_flows(load_yaml(out/'flows.yaml'),evidences,errors,warnings)
        cases=validate_cases(load_yaml(out/'cases.yaml'),flows,evidences,errors,warnings)
        validate_case_inventory_refs(cases,inventory,evidences,errors)
        cov=case_coverage(flows,cases)
        metrics={'evidence_total':total,'evidence_verified':verified,'flows':len(flows),'cases':len(cases),**cov}
        if cov['flow_coverage_ratio'] < 1.0: errors.append(f"every flow must have at least one E2E case; coverage={cov['flow_coverage_ratio']:.3f}")
        if cov['critical_branch_coverage_ratio'] < 1.0: errors.append(f"critical business branch coverage must be 100%; got {cov['critical_branch_coverage_ratio']:.3f}")
        if cov['critical_outcome_coverage_ratio'] < 1.0: errors.append(f"critical outcome coverage must be 100%; got {cov['critical_outcome_coverage_ratio']:.3f}")
        if cov['branch_coverage_ratio'] < 0.90: errors.append(f"business branch coverage must be >= 0.90; got {cov['branch_coverage_ratio']:.3f}")
        if cov['outcome_coverage_ratio'] < 0.90: errors.append(f"outcome coverage must be >= 0.90; got {cov['outcome_coverage_ratio']:.3f}")
    except Exception as exc: errors.append(str(exc))
    write_report(root,'cases',errors,warnings,metrics)
    print('E2E_SPEC_CASES_PASS' if not errors else 'E2E_SPEC_CASES_FAIL')
    for e in errors[:40]: print(f'- {e}')
    if not errors: print(json.dumps(metrics,ensure_ascii=False))
    return 1 if errors else 0

if __name__=='__main__': raise SystemExit(main())
