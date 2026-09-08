#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from e2e_validation_common import load_yaml, evidence_map, validate_flows, validate_inventory_accounting, validate_flow_inventory_refs, write_report


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root', required=True); args=ap.parse_args()
    root=Path(args.project_root).resolve(); out=root/'result'/'e2e_spec'
    errors=[]; warnings=[]; metrics={}
    try:
        inventory=load_yaml(out/'source_inventory.yaml')
        evidence_doc=load_yaml(out/'evidence_index.yaml')
        evidences,verified,total=evidence_map(root,evidence_doc,errors,warnings)
        flows_doc=load_yaml(out/'flows.yaml')
        accounting=validate_inventory_accounting(inventory,flows_doc,evidences,errors,warnings)
        flows=validate_flows(flows_doc,evidences,errors,warnings)
        validate_flow_inventory_refs(flows,inventory,errors)
        branch_total=sum(len(f.get('business_branches') or []) for f in flows.values())
        outcome_total=sum(len(f.get('outcomes') or []) for f in flows.values())
        metrics={**accounting,'evidence_total':total,'evidence_verified':verified,'evidence_verified_ratio':(verified/total if total else 0.0),'flows':len(flows),'business_branches':branch_total,'outcomes':outcome_total}
        if not flows: errors.append('no valid business flows discovered')
        if total and verified != total: errors.append(f'Flow stage requires all declared evidence to be verifiable; verified={verified}/{total}')
        if accounting.get('project_accounting_ratio',1.0) < 1.0: errors.append('all Python-inventoried projects must be analyzed or explicitly excluded')
        if accounting.get('entrypoint_accounting_ratio',1.0) < 1.0: errors.append('all Python-inventoried entrypoints must be mapped or explicitly excluded')
    except Exception as exc: errors.append(str(exc))
    write_report(root,'flows',errors,warnings,metrics)
    print('E2E_SPEC_FLOWS_PASS' if not errors else 'E2E_SPEC_FLOWS_FAIL')
    for e in errors[:40]: print(f'- {e}')
    if not errors: print(json.dumps(metrics,ensure_ascii=False))
    return 1 if errors else 0

if __name__=='__main__': raise SystemExit(main())
