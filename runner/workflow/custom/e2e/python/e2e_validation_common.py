#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

ALLOWED_PRIORITIES = {'critical', 'major', 'minor'}
ALLOWED_CASE_TYPES = {
    'happy_path', 'alternate_path', 'boundary', 'invalid_input',
    'dependency_failure', 'retry_recovery', 'idempotency', 'consistency',
}
ALLOWED_BRANCH_TYPES = {'normal', 'alternate', 'boundary', 'invalid_input', 'failure', 'retry', 'duplicate', 'consistency'}
ALLOWED_OUTCOME_TYPES = {'success', 'failure', 'rejected', 'cancelled', 'retry_exhausted', 'partial', 'other'}
ALLOWED_OBSERVE_TYPES = {'db', 'api', 'message', 'log', 'file', 'state', 'other'}
ALLOWED_EFFECT_TYPES = {'db_insert', 'db_update', 'db_delete', 'db_select', 'message_publish', 'external_call', 'file_write', 'state_change', 'other'}
ALLOWED_DEP_TYPES = {'http', 'mq', 'kafka', 'nats', 'db', 'file', 'service', 'other'}
ALLOWED_OWNERSHIP = {'sut', 'external', 'unknown'}
VAGUE_COMPLETION = {'success', 'successful', 'correct', 'works', 'works correctly', 'normal', 'expected', 'pass', 'ok'}
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f'missing required YAML: {path}')
    data = yaml.safe_load(path.read_text(encoding='utf-8', errors='replace'))
    if not isinstance(data, dict):
        raise ValueError(f'YAML root must be an object: {path}')
    return data


def text(value: Any) -> str:
    return str(value or '').strip()


def refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text(x) for x in value if text(x)]


def resolve_source(project_root: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = project_root / p
    return p.resolve()


def read_bounded(path: Path) -> tuple[str, str, str | None]:
    """Return (content, verification_status, encoding).

    Explicit evidence is only declared INVALID after a complete source read. Files too
    large for the verifier or unreadable are INCONCLUSIVE so we do not create a false
    negative merely because Python could not inspect them safely.
    """
    size=path.stat().st_size
    if size > MAX_EVIDENCE_BYTES:
        return '', 'inconclusive', None
    data=path.read_bytes()
    encodings=['utf-8-sig']
    if data.startswith((b'\xff\xfe', b'\xfe\xff')) or (data and data.count(b'\x00')/len(data) > 0.15):
        encodings.append('utf-16')
    encodings += ['cp950','big5','cp1252','latin1']
    for enc in encodings:
        try:
            return data.decode(enc), 'complete', enc
        except UnicodeDecodeError:
            continue
    return '', 'inconclusive', None


def _context_around_symbol(content: str, symbol: str, proximity_lines: int) -> tuple[str, int | None]:
    if not symbol:
        return content, None
    folded = content.casefold()
    pos = folded.find(symbol.casefold())
    if pos < 0:
        return '', None
    lines = content.splitlines()
    line_idx = content[:pos].count('\n')
    lo = max(0, line_idx - proximity_lines)
    hi = min(len(lines), line_idx + proximity_lines + 1)
    return '\n'.join(lines[lo:hi]), line_idx + 1


def evidence_map(project_root: Path, evidence_doc: dict[str, Any], errors: list[str], warnings: list[str]) -> tuple[dict[str, dict[str, Any]], int, int]:
    rows = evidence_doc.get('evidence')
    if not isinstance(rows, list) or not rows:
        errors.append("evidence_index.yaml: root 'evidence' must be a non-empty list")
        return {}, 0, 0
    out: dict[str, dict[str, Any]] = {}
    verified = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f'evidence[{i}] must be an object'); continue
        eid = text(row.get('id'))
        if not eid:
            errors.append(f'evidence[{i}] missing id'); continue
        if eid in out:
            errors.append(f'duplicate evidence id: {eid}'); continue
        raw_path = text(row.get('path')); claim = text(row.get('claim'))
        if not raw_path: errors.append(f'{eid}: missing path')
        if not claim: errors.append(f'{eid}: missing claim')
        keywords = row.get('keywords') or []
        if isinstance(keywords, str): keywords = [keywords]
        if not isinstance(keywords, list):
            errors.append(f'{eid}: keywords must be a list'); keywords=[]
        keywords = [text(k) for k in keywords if text(k)]
        symbol = text(row.get('symbol'))
        if not symbol and not keywords:
            errors.append(f'{eid}: require symbol and/or keywords so Python can verify evidence')
        mode = text(row.get('keyword_mode') or 'all').lower()
        if mode not in {'all','any'}:
            errors.append(f'{eid}: keyword_mode must be all or any'); mode='all'
        try:
            proximity = int(row.get('proximity_lines', 120))
        except (TypeError, ValueError):
            proximity = 120; errors.append(f'{eid}: proximity_lines must be integer')
        proximity = max(1, min(proximity, 1000))

        ok = bool(raw_path)
        source = resolve_source(project_root, raw_path) if raw_path else project_root/'__missing__'
        verify_status='invalid' if raw_path and not source.is_file() else 'complete'
        encoding=None
        if raw_path and not source.is_file():
            errors.append(f'{eid}: INVALID evidence file not found: {raw_path}'); ok=False; content=''
        else:
            try:
                content, verify_status, encoding = read_bounded(source) if source.is_file() else ('','invalid',None)
            except OSError as exc:
                errors.append(f'{eid}: INCONCLUSIVE cannot read evidence file {raw_path}: {exc}'); ok=False; content=''; verify_status='inconclusive'
        if verify_status == 'inconclusive':
            errors.append(f'{eid}: INCONCLUSIVE evidence file cannot be fully verified (size>{MAX_EVIDENCE_BYTES} bytes or undecodable): {raw_path}')
            ok=False
            context=''; symbol_line=None
        else:
            context, symbol_line = _context_around_symbol(content, symbol, proximity)
            if symbol and symbol_line is None:
                errors.append(f'{eid}: INVALID symbol not found in {raw_path}: {symbol}'); ok=False
            hay = (context if symbol else content).casefold()
            if keywords:
                hits = [k.casefold() in hay for k in keywords]
                kw_ok = all(hits) if mode == 'all' else any(hits)
                if not kw_ok:
                    missing=[k for k,hit in zip(keywords,hits) if not hit]
                    where=f'within ±{proximity} lines of symbol {symbol}' if symbol else 'in file'
                    errors.append(f'{eid}: INVALID keyword verification failed ({mode}) {where} in {raw_path}; unmatched={missing}')
                    ok=False
        row_copy=dict(row); row_copy['_verified']=ok; row_copy['_verification_status']='verified' if ok else ('inconclusive' if verify_status=='inconclusive' else 'invalid'); row_copy['_resolved_path']=str(source); row_copy['_symbol_line']=symbol_line; row_copy['_encoding']=encoding
        out[eid]=row_copy
        if ok: verified += 1
    return out, verified, len(out)


def validate_ref_list(owner: str, values: Any, evidences: dict[str, dict[str, Any]], errors: list[str], *, required: bool=True) -> None:
    ids=refs(values)
    if required and not ids: errors.append(f'{owner}: evidence_refs must be non-empty')
    for eid in ids:
        if eid not in evidences: errors.append(f'{owner}: unknown evidence ref {eid}')
        elif not evidences[eid].get('_verified'): errors.append(f'{owner}: evidence ref {eid} is not Python-verified')


def validate_inventory_accounting(inventory: dict[str, Any], flows_doc: dict[str, Any], evidences: dict[str, dict[str, Any]], errors: list[str], warnings: list[str]) -> dict[str, Any]:
    scope = flows_doc.get('source_scope')
    if not isinstance(scope, dict):
        errors.append('flows.yaml: source_scope must be an object'); return {}
    projects = {text(x.get('id')) for x in inventory.get('projects', []) if isinstance(x, dict) and text(x.get('id'))}
    eps = {text(x.get('id')) for x in inventory.get('entrypoint_candidates', []) if isinstance(x, dict) and text(x.get('id'))}
    analyzed = set(refs(scope.get('projects_analyzed')))
    excluded_prj = {text(x.get('project_ref')) for x in (scope.get('projects_excluded') or []) if isinstance(x, dict) and text(x.get('project_ref'))}
    mapped_eps = set(refs(scope.get('entrypoints_mapped')))
    excluded_eps = {text(x.get('entrypoint_ref')) for x in (scope.get('entrypoints_excluded') or []) if isinstance(x, dict) and text(x.get('entrypoint_ref'))}
    for row in scope.get('projects_excluded') or []:
        if isinstance(row, dict) and not text(row.get('reason')): errors.append('source_scope.projects_excluded item missing reason')
    for row in scope.get('entrypoints_excluded') or []:
        if isinstance(row, dict) and not text(row.get('reason')): errors.append('source_scope.entrypoints_excluded item missing reason')
    unknown_prj=(analyzed|excluded_prj)-projects; unknown_ep=(mapped_eps|excluded_eps)-eps
    if unknown_prj: errors.append(f'source_scope references unknown project ids: {sorted(unknown_prj)}')
    if unknown_ep: errors.append(f'source_scope references unknown entrypoint ids: {sorted(unknown_ep)}')
    missing_prj=projects-(analyzed|excluded_prj); missing_ep=eps-(mapped_eps|excluded_eps)
    if missing_prj: errors.append(f'unaccounted projects from Python inventory: {sorted(missing_prj)}')
    if missing_ep: errors.append(f'unaccounted entrypoints from Python inventory: {sorted(missing_ep)}')
    if analyzed & excluded_prj: errors.append(f'projects cannot be both analyzed and excluded: {sorted(analyzed & excluded_prj)}')
    if mapped_eps & excluded_eps: errors.append(f'entrypoints cannot be both mapped and excluded: {sorted(mapped_eps & excluded_eps)}')

    # Scanner misses are allowed only through direct, hard-verifiable evidence. This is
    # intentionally separate from inventory accounting so a legacy/dynamic entrypoint is
    # not lost merely because the regex scanner did not recognize it.
    additional_projects=scope.get('additional_projects') or []
    additional_eps=scope.get('additional_entrypoints') or []
    if not isinstance(additional_projects,list): errors.append('source_scope.additional_projects must be a list'); additional_projects=[]
    if not isinstance(additional_eps,list): errors.append('source_scope.additional_entrypoints must be a list'); additional_eps=[]
    seen_direct=set()
    for kind,rows in (('additional_projects',additional_projects),('additional_entrypoints',additional_eps)):
        for i,row in enumerate(rows):
            owner=f'source_scope.{kind}[{i}]'
            if not isinstance(row,dict): errors.append(f'{owner} must be object'); continue
            rid=text(row.get('id'))
            if not rid: errors.append(f'{owner}: id required')
            elif rid in seen_direct: errors.append(f'{owner}: duplicate direct discovery id {rid}')
            seen_direct.add(rid)
            if not text(row.get('reason')): errors.append(f'{owner}: reason required (for example scanner miss / legacy wrapper / dynamic load)')
            validate_ref_list(owner,row.get('evidence_refs'),evidences,errors)

    limitations=inventory.get('scanner_limitations') or []
    dynamic=inventory.get('dynamic_candidates') or []
    if limitations:
        warnings.append(f'Python scanner reported {len(limitations)} source limitations; scanner misses in these areas are inconclusive, not proof of absence')
    if dynamic:
        warnings.append(f'Python scanner reported {len(dynamic)} dynamic/reflection candidates requiring AI/Grill review')
    return {
        'projects_total': len(projects), 'projects_accounted': len(projects & (analyzed|excluded_prj)),
        'project_accounting_ratio': (len(projects & (analyzed|excluded_prj))/len(projects) if projects else 1.0),
        'entrypoints_total': len(eps), 'entrypoints_accounted': len(eps & (mapped_eps|excluded_eps)),
        'entrypoint_accounting_ratio': (len(eps & (mapped_eps|excluded_eps))/len(eps) if eps else 1.0),
        'additional_projects': len(additional_projects), 'additional_entrypoints': len(additional_eps),
        'scanner_limitations': len(limitations), 'dynamic_candidates': len(dynamic),
    }


def _validate_named_refs(owner: str, values: Any, allowed: set[str], field: str, errors: list[str], *, required: bool=False) -> list[str]:
    ids=refs(values)
    if required and not ids: errors.append(f'{owner}: {field} must be non-empty')
    bad=[x for x in ids if x not in allowed]
    if bad: errors.append(f'{owner}: unknown {field}: {bad}')
    return ids


def validate_flows(doc: dict[str, Any], evidences: dict[str, dict[str, Any]], errors: list[str], warnings: list[str]) -> dict[str, dict[str, Any]]:
    rows=doc.get('flows')
    if not isinstance(rows,list) or not rows:
        errors.append("flows.yaml: root 'flows' must be a non-empty list"); return {}
    flow_map={}
    for i,row in enumerate(rows):
        if not isinstance(row,dict): errors.append(f'flows[{i}] must be an object'); continue
        fid=text(row.get('id'))
        if not fid: errors.append(f'flows[{i}] missing id'); continue
        if fid in flow_map: errors.append(f'duplicate flow id: {fid}'); continue
        flow_map[fid]=row
        if not text(row.get('title')): errors.append(f'{fid}: missing title')
        if text(row.get('priority')).lower() not in ALLOWED_PRIORITIES: errors.append(f'{fid}: priority must be critical|major|minor')
        if not text(row.get('business_goal')): errors.append(f'{fid}: missing business_goal')
        trigger=row.get('trigger')
        if not isinstance(trigger,dict) or not text(trigger.get('description')): errors.append(f'{fid}: trigger.description is required')
        else: validate_ref_list(f'{fid}.trigger',trigger.get('evidence_refs'),evidences,errors)
        steps=row.get('steps')
        if not isinstance(steps,list) or not steps: errors.append(f'{fid}: steps must be non-empty')
        else:
            seen=set()
            for j,step in enumerate(steps):
                if not isinstance(step,dict): errors.append(f'{fid}.steps[{j}] must be object'); continue
                sid=text(step.get('id'))
                if not sid: errors.append(f'{fid}.steps[{j}] missing id')
                elif sid in seen: errors.append(f'{fid}: duplicate step id {sid}')
                seen.add(sid)
                if not text(step.get('action')): errors.append(f'{fid}.{sid or j}: missing action')
                validate_ref_list(f'{fid}.{sid or j}',step.get('evidence_refs'),evidences,errors)
        branches=row.get('business_branches')
        if not isinstance(branches,list) or not branches: errors.append(f'{fid}: business_branches must be non-empty')
        else:
            seen=set()
            for j,b in enumerate(branches):
                if not isinstance(b,dict): errors.append(f'{fid}.business_branches[{j}] must be object'); continue
                bid=text(b.get('id')); claim=text(b.get('claim')); btype=text(b.get('type')).lower(); pr=text(b.get('priority')).lower()
                if not bid: errors.append(f'{fid}.business_branches[{j}] missing id')
                elif bid in seen: errors.append(f'{fid}: duplicate branch id {bid}')
                seen.add(bid)
                if btype not in ALLOWED_BRANCH_TYPES: errors.append(f'{fid}.{bid or j}: invalid branch type {btype!r}')
                if pr not in ALLOWED_PRIORITIES: errors.append(f'{fid}.{bid or j}: invalid branch priority {pr!r}')
                if not claim: errors.append(f'{fid}.{bid or j}: missing branch claim')
                validate_ref_list(f'{fid}.{bid or j}',b.get('evidence_refs'),evidences,errors)
        outcomes=row.get('outcomes')
        if not isinstance(outcomes,list) or not outcomes: errors.append(f'{fid}: outcomes must be non-empty')
        else:
            seen=set(); seen_obs=set()
            for j,o in enumerate(outcomes):
                if not isinstance(o,dict): errors.append(f'{fid}.outcomes[{j}] must be object'); continue
                oid=text(o.get('id')); claim=text(o.get('claim')); otype=text(o.get('type')).lower(); pr=text(o.get('priority')).lower()
                if not oid: errors.append(f'{fid}.outcomes[{j}] missing id')
                elif oid in seen: errors.append(f'{fid}: duplicate outcome id {oid}')
                seen.add(oid)
                if otype not in ALLOWED_OUTCOME_TYPES: errors.append(f'{fid}.{oid or j}: invalid outcome type {otype!r}')
                if pr not in ALLOWED_PRIORITIES: errors.append(f'{fid}.{oid or j}: invalid outcome priority {pr!r}')
                if not claim: errors.append(f'{fid}.{oid or j}: missing outcome claim')
                elif claim.casefold() in VAGUE_COMPLETION or len(claim)<8: errors.append(f'{fid}.{oid or j}: outcome claim too vague: {claim!r}')
                validate_ref_list(f'{fid}.{oid or j}',o.get('evidence_refs'),evidences,errors)
                observe=o.get('observe_by')
                if not isinstance(observe,list) or not observe:
                    errors.append(f'{fid}.{oid or j}: observe_by must be a non-empty list so Workflow2 knows how to assert the outcome')
                    continue
                for k,obs in enumerate(observe):
                    owner=f'{fid}.{oid or j}.observe_by[{k}]'
                    if not isinstance(obs,dict): errors.append(f'{owner} must be object'); continue
                    obsid=text(obs.get('id')); typ=text(obs.get('type')).lower(); desc=text(obs.get('description'))
                    if not obsid: errors.append(f'{owner}: id required')
                    elif obsid in seen_obs: errors.append(f'{fid}: duplicate observation id {obsid}')
                    seen_obs.add(obsid)
                    if typ not in ALLOWED_OBSERVE_TYPES: errors.append(f'{owner}: invalid type {typ!r}')
                    if not desc: errors.append(f'{owner}: description required')
                    validate_ref_list(owner,obs.get('evidence_refs'),evidences,errors)
                    if typ=='log':
                        kws=obs.get('keywords') or []
                        if isinstance(kws,str): kws=[kws]
                        if not (isinstance(kws,list) and any(text(x) for x in kws)) and not text(obs.get('regex')):
                            errors.append(f'{owner}: log observation requires keywords and/or regex')
                    elif typ=='db':
                        if not text(obs.get('target')) and not text(obs.get('sql_ref')): errors.append(f'{owner}: db observation requires target and/or sql_ref')
                    elif typ=='api':
                        if not text(obs.get('target')): errors.append(f'{owner}: api observation requires target/endpoint')
                    elif typ=='message':
                        if not text(obs.get('target')): errors.append(f'{owner}: message observation requires target/channel')
                    elif typ=='file':
                        if not text(obs.get('target')): errors.append(f'{owner}: file observation requires target/path')
        # Optional test-contract metadata. Keep strict enough to prevent invented references,
        # but do not force every flow to use every section.
        effects=row.get('data_effects') or []
        if not isinstance(effects,list): errors.append(f'{fid}: data_effects must be a list'); effects=[]
        for j,e in enumerate(effects):
            owner=f'{fid}.data_effects[{j}]'
            if not isinstance(e,dict): errors.append(f'{owner} must be object'); continue
            if text(e.get('type')).lower() not in ALLOWED_EFFECT_TYPES: errors.append(f'{owner}: invalid effect type {text(e.get("type"))!r}')
            if not text(e.get('target')): errors.append(f'{owner}: target required')
            validate_ref_list(owner,e.get('evidence_refs'),evidences,errors)
        deps=row.get('external_dependencies') or []
        if not isinstance(deps,list): errors.append(f'{fid}: external_dependencies must be a list'); deps=[]
        for j,d in enumerate(deps):
            owner=f'{fid}.external_dependencies[{j}]'
            if not isinstance(d,dict): errors.append(f'{owner} must be object'); continue
            if text(d.get('type')).lower() not in ALLOWED_DEP_TYPES: errors.append(f'{owner}: invalid dependency type {text(d.get("type"))!r}')
            if not text(d.get('target')): errors.append(f'{owner}: target required')
            own=text(d.get('ownership')).lower()
            if own not in ALLOWED_OWNERSHIP: errors.append(f'{owner}: ownership must be sut|external|unknown')
            validate_ref_list(owner,d.get('evidence_refs'),evidences,errors)
        params=row.get('parameters') or []
        if not isinstance(params,list): errors.append(f'{fid}: parameters must be a list'); params=[]
        for j,param in enumerate(params):
            owner=f'{fid}.parameters[{j}]'
            if not isinstance(param,dict): errors.append(f'{owner} must be object'); continue
            inv_ref=text(param.get('inventory_ref'))
            direct_refs=refs(param.get('evidence_refs'))
            if not inv_ref and not direct_refs:
                errors.append(f'{owner}: require inventory_ref and/or evidence_refs; scanner miss must not erase a real parameter')
            if direct_refs:
                validate_ref_list(owner,param.get('evidence_refs'),evidences,errors)
            if text(param.get('source')).lower() not in {'system','user','config'}: errors.append(f'{owner}: source must be system|user|config')
            if not text(param.get('role')): errors.append(f'{owner}: role required')
        behavior=row.get('behavior') or {}
        if behavior and not isinstance(behavior,dict): errors.append(f'{fid}: behavior must be object')
    return flow_map

def flow_branch_ids(flow: dict[str, Any]) -> set[str]:
    return {text(x.get('id')) for x in flow.get('business_branches') or [] if isinstance(x,dict) and text(x.get('id'))}


def flow_outcome_ids(flow: dict[str, Any]) -> set[str]:
    return {text(x.get('id')) for x in flow.get('outcomes') or [] if isinstance(x,dict) and text(x.get('id'))}


def flow_observation_ids(flow: dict[str, Any], outcome_refs: set[str] | None = None) -> set[str]:
    out=set()
    wanted=outcome_refs
    for outcome in flow.get('outcomes') or []:
        if not isinstance(outcome,dict): continue
        oid=text(outcome.get('id'))
        if wanted is not None and oid not in wanted: continue
        for obs in outcome.get('observe_by') or []:
            if isinstance(obs,dict) and text(obs.get('id')): out.add(text(obs.get('id')))
    return out


def flow_observations(flow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out={}
    for outcome in flow.get('outcomes') or []:
        if not isinstance(outcome,dict): continue
        for obs in outcome.get('observe_by') or []:
            if isinstance(obs,dict) and text(obs.get('id')): out[text(obs.get('id'))]=obs
    return out


def validate_cases(doc: dict[str, Any], flows: dict[str, dict[str, Any]], evidences: dict[str, dict[str, Any]], errors: list[str], warnings: list[str]) -> dict[str, dict[str, Any]]:
    rows=doc.get('cases')
    if not isinstance(rows,list) or not rows:
        errors.append("cases.yaml: root 'cases' must be a non-empty list"); return {}
    case_map={}; fingerprints={}; happy_by_flow=set()
    for i,row in enumerate(rows):
        if not isinstance(row,dict): errors.append(f'cases[{i}] must be object'); continue
        cid=text(row.get('id'))
        if not cid: errors.append(f'cases[{i}] missing id'); continue
        if cid in case_map: errors.append(f'duplicate case id: {cid}'); continue
        case_map[cid]=row
        fid=text(row.get('flow_ref')); flow=flows.get(fid)
        if flow is None: errors.append(f'{cid}: unknown flow_ref {fid!r}')
        ctype=text(row.get('type')).lower(); priority=text(row.get('priority')).lower()
        if ctype not in ALLOWED_CASE_TYPES: errors.append(f'{cid}: invalid type {ctype!r}')
        if priority not in ALLOWED_PRIORITIES: errors.append(f'{cid}: priority must be critical|major|minor')
        if not text(row.get('title')): errors.append(f'{cid}: missing title')
        if not text(row.get('business_reason')): errors.append(f'{cid}: missing business_reason')
        if not text(row.get('trigger')): errors.append(f'{cid}: missing trigger')
        branch_refs=refs(row.get('branch_refs')); outcome_refs=refs(row.get('expected_outcome_refs')); observation_refs=refs(row.get('observation_refs'))
        if not branch_refs: errors.append(f'{cid}: branch_refs must be non-empty')
        if not outcome_refs: errors.append(f'{cid}: expected_outcome_refs must be non-empty')
        if not observation_refs: errors.append(f'{cid}: observation_refs must be non-empty; E2E case must declare how the outcome is observed')
        if flow is not None:
            badb=[x for x in branch_refs if x not in flow_branch_ids(flow)]
            bado=[x for x in outcome_refs if x not in flow_outcome_ids(flow)]
            allowed_obs=flow_observation_ids(flow,set(outcome_refs))
            bado2=[x for x in observation_refs if x not in allowed_obs]
            if badb: errors.append(f'{cid}: branch refs do not belong to {fid}: {badb}')
            if bado: errors.append(f'{cid}: outcome refs do not belong to {fid}: {bado}')
            if bado2: errors.append(f'{cid}: observation refs do not belong to expected outcomes of {fid}: {bado2}')
            if ctype=='happy_path': happy_by_flow.add(fid)
        validate_ref_list(cid,row.get('evidence_refs'),evidences,errors)
        fp=(fid,ctype,re.sub(r'\s+',' ',text(row.get('trigger')).casefold()),tuple(sorted(branch_refs)),tuple(sorted(outcome_refs)),tuple(sorted(observation_refs)))
        if fp in fingerprints: errors.append(f'{cid}: probable duplicate of {fingerprints[fp]}')
        else: fingerprints[fp]=cid
    for fid,flow in flows.items():
        if text(flow.get('priority')).lower()=='critical' and fid not in happy_by_flow:
            errors.append(f'{fid}: critical flow requires at least one happy_path case')
    return case_map


def case_coverage(flows: dict[str,dict[str,Any]], cases: dict[str,dict[str,Any]]) -> dict[str,Any]:
    flow_refs={text(c.get('flow_ref')) for c in cases.values()}
    covered_branches=set(); covered_outcomes=set()
    all_branches=set(); critical_branches=set(); all_outcomes=set(); critical_outcomes=set()
    for fid,f in flows.items():
        for b in f.get('business_branches') or []:
            if isinstance(b,dict) and text(b.get('id')):
                key=(fid,text(b.get('id'))); all_branches.add(key)
                if text(b.get('priority')).lower()=='critical': critical_branches.add(key)
        for o in f.get('outcomes') or []:
            if isinstance(o,dict) and text(o.get('id')):
                key=(fid,text(o.get('id'))); all_outcomes.add(key)
                if text(o.get('priority')).lower()=='critical': critical_outcomes.add(key)
    for c in cases.values():
        fid=text(c.get('flow_ref'))
        covered_branches |= {(fid,x) for x in refs(c.get('branch_refs'))}
        covered_outcomes |= {(fid,x) for x in refs(c.get('expected_outcome_refs'))}
    ratio=lambda a,b: (len(a & b)/len(b) if b else 1.0)
    return {
        'flows_total': len(flows), 'flows_covered': len(set(flows)&flow_refs), 'flow_coverage_ratio': (len(set(flows)&flow_refs)/len(flows) if flows else 0.0),
        'branches_total': len(all_branches), 'branches_covered': len(all_branches & covered_branches), 'branch_coverage_ratio': ratio(covered_branches,all_branches),
        'critical_branches_total': len(critical_branches), 'critical_branches_covered': len(critical_branches & covered_branches), 'critical_branch_coverage_ratio': ratio(covered_branches,critical_branches),
        'outcomes_total': len(all_outcomes), 'outcomes_covered': len(all_outcomes & covered_outcomes), 'outcome_coverage_ratio': ratio(covered_outcomes,all_outcomes),
        'critical_outcomes_total': len(critical_outcomes), 'critical_outcomes_covered': len(critical_outcomes & covered_outcomes), 'critical_outcome_coverage_ratio': ratio(covered_outcomes,critical_outcomes),
    }


def canonical_hash(value: Any) -> str:
    payload=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _map_by_id(rows: Any) -> dict[str,dict[str,Any]]:
    return {text(x.get('id')): x for x in (rows or []) if isinstance(x,dict) and text(x.get('id'))}


def validate_final(final_doc: dict[str, Any], source_flows: dict[str, dict[str, Any]], source_cases: dict[str, dict[str, Any]], source_evidence: dict[str, dict[str, Any]], errors: list[str], warnings: list[str]) -> None:
    final_flows=_map_by_id(final_doc.get('flows')); final_cases=_map_by_id(final_doc.get('cases')); final_evidence=_map_by_id(final_doc.get('evidence'))
    if set(final_flows)!=set(source_flows): errors.append(f'final flow ids differ from flows.yaml; missing={sorted(set(source_flows)-set(final_flows))}, extra={sorted(set(final_flows)-set(source_flows))}')
    if set(final_cases)!=set(source_cases): errors.append(f'final case ids differ from cases.yaml; missing={sorted(set(source_cases)-set(final_cases))}, extra={sorted(set(final_cases)-set(source_cases))}')
    if set(final_evidence)!=set(source_evidence): errors.append(f'final evidence ids differ from evidence_index.yaml; missing={sorted(set(source_evidence)-set(final_evidence))}, extra={sorted(set(final_evidence)-set(source_evidence))}')
    for fid,src in source_flows.items():
        if fid in final_flows and canonical_hash(final_flows[fid]) != canonical_hash(src): errors.append(f'{fid}: final flow content differs from verified flows.yaml')
    for cid,src in source_cases.items():
        if cid in final_cases and canonical_hash(final_cases[cid]) != canonical_hash(src): errors.append(f'{cid}: final case content differs from verified cases.yaml')
    for eid,src in source_evidence.items():
        if eid in final_evidence:
            clean={k:v for k,v in src.items() if not k.startswith('_')}
            if canonical_hash(final_evidence[eid]) != canonical_hash(clean): errors.append(f'{eid}: final evidence content differs from evidence_index.yaml')
    coverage=final_doc.get('coverage')
    if not isinstance(coverage,dict): errors.append('final coverage must be an object'); return
    cov=case_coverage(source_flows,source_cases)
    expected={
        'total_flows': len(source_flows),
        'critical_flows': sum(text(f.get('priority')).lower()=='critical' for f in source_flows.values()),
        'flows_with_cases': cov['flows_covered'],
        'business_branches_total': cov['branches_total'],
        'business_branches_covered': cov['branches_covered'],
        'outcomes_total': cov['outcomes_total'],
        'outcomes_covered': cov['outcomes_covered'],
    }
    for k,v in expected.items():
        if coverage.get(k)!=v: errors.append(f'coverage.{k} must be {v}, got {coverage.get(k)!r}')


def write_report(root: Path, stage: str, errors: list[str], warnings: list[str], metrics: dict[str, Any]) -> None:
    report=root/'result'/'e2e_spec'/'validation'/f'{stage}.json'; report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps({'stage':stage,'status':'FAIL' if errors else 'PASS','errors':errors,'warnings':warnings,'metrics':metrics},ensure_ascii=False,indent=2),encoding='utf-8')


def validate_flow_inventory_refs(flows: dict[str,dict[str,Any]], inventory: dict[str,Any], errors: list[str]) -> None:
    sql_ids={text(x.get('id')) for x in inventory.get('sql_operations',[]) if isinstance(x,dict) and text(x.get('id'))}
    integration_ids={text(x.get('id')) for x in inventory.get('integration_candidates',[]) if isinstance(x,dict) and text(x.get('id'))}
    log_ids={text(x.get('id')) for x in inventory.get('log_candidates',[]) if isinstance(x,dict) and text(x.get('id'))}
    system_ids={text(x.get('id')) for key in ('system_parameters','config_keys') for x in inventory.get(key,[]) if isinstance(x,dict) and text(x.get('id'))}
    user_ids={text(x.get('id')) for x in inventory.get('user_input_parameters',[]) if isinstance(x,dict) and text(x.get('id'))}
    all_param_ids=system_ids|user_ids
    for fid,flow in flows.items():
        for field,allowed in (('related_sql_refs',sql_ids),('related_system_parameter_refs',system_ids),('related_user_input_parameter_refs',user_ids),('related_log_refs',log_ids)):
            bad=[x for x in refs(flow.get(field)) if x not in allowed]
            if bad: errors.append(f'{fid}: unknown {field}: {bad}')
        for i,p in enumerate(flow.get('parameters') or []):
            if isinstance(p,dict):
                ref=text(p.get('inventory_ref'))
                # Inventory is assistive: if AI provides a ref it must be real, but a
                # scanner miss may be represented with direct evidence_refs instead.
                if ref and ref not in all_param_ids: errors.append(f'{fid}.parameters[{i}]: unknown inventory_ref {ref!r}')
        for i,d in enumerate(flow.get('external_dependencies') or []):
            if isinstance(d,dict) and text(d.get('integration_ref')) and text(d.get('integration_ref')) not in integration_ids:
                errors.append(f'{fid}.external_dependencies[{i}]: unknown integration_ref {text(d.get("integration_ref"))!r}')
        for outcome in flow.get('outcomes') or []:
            if not isinstance(outcome,dict): continue
            oid=text(outcome.get('id'))
            for i,obs in enumerate(outcome.get('observe_by') or []):
                if not isinstance(obs,dict): continue
                if text(obs.get('sql_ref')) and text(obs.get('sql_ref')) not in sql_ids:
                    errors.append(f'{fid}.{oid}.observe_by[{i}]: unknown sql_ref {text(obs.get("sql_ref"))!r}')
                if text(obs.get('log_ref')) and text(obs.get('log_ref')) not in log_ids:
                    errors.append(f'{fid}.{oid}.observe_by[{i}]: unknown log_ref {text(obs.get("log_ref"))!r}')

def validate_case_inventory_refs(cases: dict[str,dict[str,Any]], inventory: dict[str,Any], evidences: dict[str,dict[str,Any]], errors: list[str]) -> None:
    sql_ids={text(x.get('id')) for x in inventory.get('sql_operations',[]) if isinstance(x,dict) and text(x.get('id'))}
    param_ids={text(x.get('id')) for key in ('system_parameters','config_keys','user_input_parameters') for x in inventory.get(key,[]) if isinstance(x,dict) and text(x.get('id'))}
    for cid,case in cases.items():
        assertions=case.get('sql_assertions') or []
        if not isinstance(assertions,list): errors.append(f'{cid}: sql_assertions must be a list'); assertions=[]
        for i,row in enumerate(assertions):
            if not isinstance(row,dict): errors.append(f'{cid}.sql_assertions[{i}] must be object'); continue
            owner=f'{cid}.sql_assertions[{i}]'
            ref=text(row.get('inventory_ref'))
            direct_refs=refs(row.get('evidence_refs'))
            if ref and ref not in sql_ids: errors.append(f'{owner}: unknown SQL inventory_ref {ref!r}')
            if not ref and not direct_refs: errors.append(f'{owner}: require inventory_ref and/or evidence_refs')
            if direct_refs: validate_ref_list(owner,row.get('evidence_refs'),evidences,errors)
            if not text(row.get('expectation')): errors.append(f'{owner}: expectation required')
        variations=case.get('parameter_variations') or []
        if not isinstance(variations,list): errors.append(f'{cid}: parameter_variations must be a list'); variations=[]
        for i,row in enumerate(variations):
            if not isinstance(row,dict): errors.append(f'{cid}.parameter_variations[{i}] must be object'); continue
            owner=f'{cid}.parameter_variations[{i}]'
            ref=text(row.get('inventory_ref'))
            direct_refs=refs(row.get('evidence_refs'))
            if ref and ref not in param_ids: errors.append(f'{owner}: unknown parameter inventory_ref {ref!r}')
            if not ref and not direct_refs: errors.append(f'{owner}: require inventory_ref and/or evidence_refs')
            if direct_refs: validate_ref_list(owner,row.get('evidence_refs'),evidences,errors)
            if not text(row.get('value_class')): errors.append(f'{owner}: value_class required')
