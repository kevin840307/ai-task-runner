#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
import yaml


def t(v: Any) -> str:
    return str(v or '').strip()


def bullets(values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        return ['- （無）']
    out=[]
    for v in values:
        if isinstance(v, dict):
            out.append('- ' + ', '.join(f'{k}={t(val)}' for k,val in v.items()))
        else:
            out.append(f'- {t(v)}')
    return out


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root', required=True); args=ap.parse_args()
    root=Path(args.project_root).resolve(); src=root/'result'/'e2e_spec'/'e2e_spec.yaml'; dst=root/'result'/'e2e_spec'/'e2e_spec.md'
    if not src.is_file(): print(f'missing final spec: {src}'); return 1
    doc=yaml.safe_load(src.read_text(encoding='utf-8')) or {}
    flows={t(f.get('id')):f for f in doc.get('flows',[]) if isinstance(f,dict)}
    lines=['# E2E Regression SPEC','', '> 此 Markdown 由 `e2e_spec.yaml` 產生；YAML 才是 Source of Truth。','']
    cov=doc.get('coverage') or {}
    lines += ['## Coverage Summary','']
    for key in ('total_flows','critical_flows','flows_with_cases','business_branches_total','business_branches_covered','outcomes_total','outcomes_covered'):
        lines.append(f'- **{key}**: {cov.get(key, "")}')
    lines += ['', '## Business Flows','']
    for flow in doc.get('flows',[]) or []:
        if not isinstance(flow,dict): continue
        lines += [f"### {t(flow.get('id'))} — {t(flow.get('title'))}",'',f"**Priority:** {t(flow.get('priority'))}",'',f"**Business Goal:** {t(flow.get('business_goal'))}",'']
        trig=flow.get('trigger') or {}; lines += [f"**Trigger:** {t(trig.get('description'))}",'','**Steps:**']
        for step in flow.get('steps',[]) or []:
            if isinstance(step,dict): lines.append(f"- {t(step.get('id'))}: {t(step.get('action'))}")
        lines += ['', '**Business Branches:**']
        for b in flow.get('business_branches',[]) or []:
            if isinstance(b,dict): lines.append(f"- {t(b.get('id'))} [{t(b.get('type'))}/{t(b.get('priority'))}]: {t(b.get('claim'))}")
        lines += ['', '**Outcomes:**']
        for o in flow.get('outcomes',[]) or []:
            if isinstance(o,dict):
                lines.append(f"- {t(o.get('id'))} [{t(o.get('type'))}/{t(o.get('priority'))}]: {t(o.get('claim'))}")
                for obs in o.get('observe_by',[]) or []:
                    if isinstance(obs,dict):
                        detail=t(obs.get('description'))
                        if t(obs.get('type')).lower()=='log':
                            extra=[]
                            if obs.get('keywords'): extra.append('keywords=' + ', '.join(map(str,obs.get('keywords') or [])))
                            if obs.get('regex'): extra.append('regex=' + t(obs.get('regex')))
                            if obs.get('correlation_key'): extra.append('correlation=' + t(obs.get('correlation_key')))
                            if extra: detail += ' (' + '; '.join(extra) + ')'
                        lines.append(f"  - observe {t(obs.get('id'))} [{t(obs.get('type'))}]: {detail}")
        for label,key in [('Related SQL','related_sql_refs'),('Related Logs','related_log_refs'),('System Parameters','related_system_parameter_refs'),('User Input Parameters','related_user_input_parameter_refs')]:
            vals=flow.get(key) or []
            if vals:
                lines += ['', f'**{label}:**'] + bullets(vals)
        if flow.get('data_effects'):
            lines += ['', '**Data Effects:**'] + bullets(flow.get('data_effects'))
        if flow.get('external_dependencies'):
            lines += ['', '**External Dependencies:**'] + bullets(flow.get('external_dependencies'))
        if flow.get('parameters'):
            lines += ['', '**Parameter Model:**'] + bullets(flow.get('parameters'))
        if flow.get('behavior'):
            lines += ['', '**Behavior:**'] + bullets([flow.get('behavior')])
        lines.append('')
    lines += ['## E2E Cases','']
    for case in doc.get('cases',[]) or []:
        if not isinstance(case,dict): continue
        fid=t(case.get('flow_ref'))
        lines += [f"### {t(case.get('id'))} — {t(case.get('title'))}",'',f"**Flow:** {fid} — {t(flows.get(fid,{}).get('title'))}",f"**Type:** {t(case.get('type'))}",f"**Priority:** {t(case.get('priority'))}",'',f"**Business Reason:** {t(case.get('business_reason'))}",'','**Preconditions:**']
        lines += bullets(case.get('preconditions'))
        lines += ['',f"**Trigger:** {t(case.get('trigger'))}",'','**Branch Refs:**'] + bullets(case.get('branch_refs'))
        lines += ['','**Expected Path:**'] + bullets(case.get('expected_path'))
        lines += ['','**Expected Outcome Refs:**'] + bullets(case.get('expected_outcome_refs'))
        lines += ['','**Observation Refs:**'] + bullets(case.get('observation_refs'))
        if case.get('sql_assertions'): lines += ['','**SQL Assertions:**'] + bullets(case.get('sql_assertions'))
        if case.get('parameter_variations'): lines += ['','**Parameter Variations:**'] + bullets(case.get('parameter_variations'))
        lines.append('')
    dst.parent.mkdir(parents=True,exist_ok=True); dst.write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8')
    print(f'E2E_SPEC_MD_WRITTEN {dst}'); return 0

if __name__=='__main__': raise SystemExit(main())
