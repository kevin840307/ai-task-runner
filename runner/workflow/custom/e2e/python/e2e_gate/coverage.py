from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple
from .models import GateResult, GateStatus, GateViolation

ALLOWED_DISPOSITIONS = {'CONFIRMED','REQUIRED','NON_E2E','EXCLUDED','REVIEW_REQUIRED','CONFLICT','EXTERNAL','RESOLVED','SUPPORT_ONLY'}




def canonical_analysis_unit_key(project_ref: str, unit_type: str, seed: Mapping[str, Any], primary_hint_ref: str | None=None) -> str:
    # Deterministic entrypoint hints own leaf-unit identity. AI-provided seed remains an audit locator,
    # but wording/path-shape drift must not change the AU id for the same discovered entrypoint.
    if primary_hint_ref:
        return f"{project_ref}|primary_hint={primary_hint_ref}"
    parts=[]
    for k in sorted(seed or {}):
        v=(seed or {}).get(k)
        if v in (None,'',[]):
            continue
        if isinstance(v,str):
            v=' '.join(v.replace('\\','/').split())
        else:
            v=json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
        parts.append(f'{k}={v}')
    return f"{project_ref}|{unit_type}|{'|'.join(parts)}"


def canonical_behavior_key(analysis_unit_ref: str) -> str:
    return f'{analysis_unit_ref}|local'



def canonicalize_analysis_units(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize AI Stage-0 unit proposals into Python-owned persisted artifacts.

    AI owns decomposition fields; Python owns semantic_key/id. Deprecated duplicate
    fields are intentionally dropped so one fact has one authoritative representation.
    """
    out=[]
    for raw in items:
        unit=dict(raw)
        unit.pop('source_refs', None)
        unit.pop('child_units', None)
        unit.pop('parent_unit_ref', None)
        key=canonical_analysis_unit_key(
            str(unit.get('project_ref') or ''),
            str(unit.get('type') or ''),
            unit.get('seed') if isinstance(unit.get('seed'), Mapping) else {},
            unit.get('primary_hint_ref'),
        )
        unit['semantic_key']=key
        unit['id']=stable_id('AU', key)
        out.append(unit)
    return out


def canonicalize_behaviors(items: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize AI Stage-1 behavior proposals into Python-owned persisted artifacts.

    `project`, top-level `evidence_refs`, merge lineage and free-form IDs are redundant.
    Project is derived from the Analysis Unit; evidence refs are derived from claims.
    """
    out=[]
    for raw in items:
        b=dict(raw)
        b.pop('project', None)
        b.pop('evidence_refs', None)
        b.pop('source_behavior_refs', None)
        key=canonical_behavior_key(str(b.get('analysis_unit_ref') or ''))
        b['semantic_key']=key
        b['id']=stable_id('BEH', key)
        out.append(b)
    return out

def stable_id(prefix: str, *parts: Any, length: int = 12) -> str:
    canonical = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:length].upper()
    return f'{prefix}-{digest}'

def artifact_fingerprint(*artifacts: Any) -> str:
    canonical=json.dumps(artifacts,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest().upper()


def closure_gate(name: str, expected_ids: Iterable[str], dispositions: Mapping[str, Any], repair_from: str) -> GateResult:
    expected=set(expected_ids); accounted=set(); bad={}; unknown=set(dispositions)-expected
    for k,raw in dispositions.items():
        status=raw.get('status') if isinstance(raw,dict) else raw
        if status in ALLOWED_DISPOSITIONS: accounted.add(k)
        else: bad[k]=status
    missing=expected-accounted; violations=[]
    if missing: violations.append(GateViolation('CLOSURE_UNACCOUNTED', f'Unaccounted inputs: {sorted(missing)}', None, repair_from, 'CRITICAL', {'missing':sorted(missing)}))
    if unknown: violations.append(GateViolation('CLOSURE_UNKNOWN_INPUT', f'Dispositions reference unknown inputs: {sorted(unknown)}', None, repair_from))
    if bad: violations.append(GateViolation('CLOSURE_BAD_DISPOSITION', f'Invalid dispositions: {bad}', None, repair_from))
    accounted_expected=expected & accounted
    coverage=len(accounted_expected)/len(expected) if expected else 1.0
    return GateResult(name, GateStatus.FAIL if violations else GateStatus.PASS, violations, {'expected':len(expected),'accounted':len(accounted_expected),'unaccounted':len(missing),'coverage':coverage})


def analysis_unit_gate(project_ids:Set[str], analysis_units:Sequence[Dict[str,Any]], project_dispositions:Mapping[str,Any], *, baseline_ids:Set[str]|None=None)->GateResult:
    violations=[]; unit_ids=set(); projects_with_units=set(); baseline_ids=set(baseline_ids or set())
    for u in analysis_units:
        uid=u.get('id')
        if not uid: violations.append(GateViolation('ANALYSIS_UNIT_NO_ID','Analysis unit missing id',None,'system_discovery')); continue
        if uid in unit_ids: violations.append(GateViolation('ANALYSIS_UNIT_DUPLICATE_ID',uid,uid,'system_discovery'))
        unit_ids.add(uid); pref=u.get('project_ref')
        if pref not in project_ids: violations.append(GateViolation('ANALYSIS_UNIT_UNKNOWN_PROJECT',str(pref),uid,'system_discovery'))
        else: projects_with_units.add(pref)
        if u.get('status')=='EXCLUDED' and not u.get('reason'): violations.append(GateViolation('ANALYSIS_UNIT_EXCLUSION_NO_REASON','EXCLUDED requires reason',uid,'system_discovery'))
        refs=set(u.get('baseline_refs',[]) or [])
        if baseline_ids:
            bad_refs=refs-baseline_ids
            if bad_refs: violations.append(GateViolation('ANALYSIS_UNIT_UNKNOWN_BASELINE_REF',f'Unknown baseline refs: {sorted(bad_refs)}',uid,'system_discovery','CRITICAL'))
            if pref in project_ids and pref not in refs:
                violations.append(GateViolation('ANALYSIS_UNIT_MISSING_PROJECT_BASELINE',f'Analysis unit must include its project_ref in baseline_refs: {pref}',uid,'system_discovery','CRITICAL'))
    base=closure_gate('project_closure',project_ids,project_dispositions,'system_discovery'); violations.extend(base.violations)
    for pid in project_ids:
        raw=project_dispositions.get(pid); status=raw.get('status') if isinstance(raw,dict) else raw
        reason=raw.get('reason') if isinstance(raw,dict) else None
        if status=='EXCLUDED':
            violations.append(GateViolation('PROJECT_EXCLUSION_FORBIDDEN','Deterministic project candidates cannot be EXCLUDED before analysis',pid,'system_discovery','CRITICAL'))
        if status in {'NON_E2E','REVIEW_REQUIRED','CONFLICT'} and not (isinstance(reason,str) and reason.strip()):
            violations.append(GateViolation('PROJECT_DISPOSITION_NO_REASON',f'{status} requires a concrete reason',pid,'system_discovery'))
        if pid not in projects_with_units:
            violations.append(GateViolation('PROJECT_NO_ANALYSIS_UNIT',f'Every deterministic project candidate requires at least one analysis unit before final classification: {pid}',pid,'system_discovery','CRITICAL'))
    unresolved=any(((raw.get('status') if isinstance(raw,dict) else raw) in {'REVIEW_REQUIRED','CONFLICT'}) for raw in project_dispositions.values()) or any(u.get('status') in {'REVIEW_REQUIRED','CONFLICT'} for u in analysis_units)
    status=GateStatus.FAIL if violations else GateStatus.REVIEW_REQUIRED if unresolved else GateStatus.PASS
    return GateResult('system_discovery_gate',status,violations,{**base.metrics,'analysis_units':len(unit_ids)})


def analysis_unit_behavior_closure_gate(analysis_unit_ids:Set[str], behaviors:Sequence[Dict[str,Any]], unit_dispositions:Mapping[str,Any])->GateResult:
    violations=[]; behavior_by_unit={}
    for b in behaviors:
        ref=b.get('analysis_unit_ref')
        if ref not in analysis_unit_ids: violations.append(GateViolation('BEHAVIOR_UNKNOWN_ANALYSIS_UNIT',str(ref),b.get('id'),'behavior_discovery'))
        else: behavior_by_unit.setdefault(ref,[]).append(b.get('id'))
    base=closure_gate('analysis_unit_closure',analysis_unit_ids,unit_dispositions,'behavior_discovery'); violations.extend(base.violations)
    for uid in analysis_unit_ids:
        raw=unit_dispositions.get(uid); status=raw.get('status') if isinstance(raw,dict) else raw
        if status in {'CONFIRMED','REQUIRED','RESOLVED'} and not behavior_by_unit.get(uid):
            violations.append(GateViolation('ANALYSIS_UNIT_NO_BEHAVIOR',f'Confirmed unit has no behavior: {uid}',uid,'behavior_discovery','CRITICAL'))
    unresolved=any(((raw.get('status') if isinstance(raw,dict) else raw) in {'REVIEW_REQUIRED','CONFLICT'}) for raw in unit_dispositions.values())
    status=GateStatus.FAIL if violations else GateStatus.REVIEW_REQUIRED if unresolved else GateStatus.PASS
    return GateResult('behavior_unit_closure',status,violations,base.metrics)


def boundary_closure_gate(boundary_ids:Set[str], boundary_dispositions:Mapping[str,Any])->GateResult:
    return closure_gate('boundary_closure',boundary_ids,boundary_dispositions,'flow_resolution')


def testable_element_gate(elements:Sequence[Dict[str,Any]], candidate_ids:Set[str], candidate_dispositions:Mapping[str,Any])->GateResult:
    violations=[]; ids=set(); lineage={}
    for e in elements:
        eid=e.get('id')
        if not eid: violations.append(GateViolation('TESTABLE_ELEMENT_NO_ID','Missing id',None,'testable_universe')); continue
        if eid in ids: violations.append(GateViolation('TESTABLE_ELEMENT_DUPLICATE_ID',eid,eid,'testable_universe'))
        ids.add(eid)
        for c in e.get('candidate_refs',[]) or []: lineage.setdefault(c,set()).add(eid)
    base=closure_gate('testable_candidate_closure',candidate_ids,candidate_dispositions,'testable_universe'); violations.extend(base.violations)
    for cid in candidate_ids:
        raw=candidate_dispositions.get(cid); status=raw.get('status') if isinstance(raw,dict) else raw
        result_refs=set(raw.get('result_refs',[])) if isinstance(raw,dict) else set()
        if status in {'REQUIRED','CONFIRMED','RESOLVED'}:
            mapped=result_refs | lineage.get(cid,set())
            if not mapped: violations.append(GateViolation('TESTABLE_CANDIDATE_NO_LINEAGE',f'Accepted candidate has no result element: {cid}',cid,'testable_universe','CRITICAL'))
            bad=mapped-ids
            if bad: violations.append(GateViolation('TESTABLE_CANDIDATE_BAD_LINEAGE',f'Unknown result elements: {sorted(bad)}',cid,'testable_universe'))
    required={e.get('id') for e in elements if e.get('e2e_relevance')=='REQUIRED'}; review={e.get('id') for e in elements if e.get('e2e_relevance')=='REVIEW_REQUIRED'}
    status=GateStatus.FAIL if violations else GateStatus.REVIEW_REQUIRED if review else GateStatus.PASS
    return GateResult('testable_universe_gate',status,violations,{**base.metrics,'elements':len(ids),'required_elements':len(required),'review_required_elements':len(review)})


def obligation_element_closure_gate(required_element_ids:Set[str], obligations:Sequence[Dict[str,Any]])->GateResult:
    covered=set()
    for o in obligations: covered.update(o.get('element_refs',[]) or [])
    missing=required_element_ids-covered; violations=[]
    if missing: violations.append(GateViolation('MISSING_TESTABLE_ELEMENT_OBLIGATION',f'Required elements without obligation: {sorted(missing)}',None,'testable_universe','CRITICAL',{'missing':sorted(missing)}))
    cov=len(required_element_ids&covered)/len(required_element_ids) if required_element_ids else 1.0
    return GateResult('obligation_element_closure',GateStatus.FAIL if violations else GateStatus.PASS,violations,{'testable_element_coverage':cov})


def _pairs(rules:Mapping[str,Any]|None)->Set[frozenset[str]]:
    out=set()
    for p in (rules or {}).get('incompatible_obligation_pairs',[]) or []:
        if isinstance(p,(list,tuple)) and len(p)==2: out.add(frozenset(map(str,p)))
    return out


def select_scenarios(candidates:Sequence[Dict[str,Any]], obligation_ids:Set[str], compatibility_rules:Mapping[str,Any]|None=None)->Tuple[List[Dict[str,Any]],GateResult]:
    """Deterministic greedy set-cover with hard compatibility validation and stable tie-break."""
    valid=[]; violations=[]; incompatible_pairs=_pairs(compatibility_rules); keys=set()
    for c in candidates:
        key=str(c.get('semantic_key') or '')
        if not key: violations.append(GateViolation('SCENARIO_CANDIDATE_NO_KEY','semantic_key required',None,'scenario_planning')); continue
        if key in keys: violations.append(GateViolation('SCENARIO_CANDIDATE_DUPLICATE_KEY',key,key,'scenario_planning')); continue
        keys.add(key); covers=set(c.get('covers',[]) or []); unknown=covers-obligation_ids
        if unknown: violations.append(GateViolation('SCENARIO_CANDIDATE_UNKNOWN_OBLIGATION',str(sorted(unknown)),key,'scenario_planning')); continue
        if not covers: violations.append(GateViolation('SCENARIO_CANDIDATE_EMPTY_COVERAGE','Candidate covers nothing',key,'scenario_planning')); continue
        for pair in incompatible_pairs:
            if pair <= covers: violations.append(GateViolation('SCENARIO_CANDIDATE_INCOMPATIBLE_OBLIGATIONS',str(sorted(pair)),key,'scenario_planning','CRITICAL'))
        if c.get('review_required'): violations.append(GateViolation('SCENARIO_CANDIDATE_REVIEW_REQUIRED','Candidate cannot enter deterministic solver while review_required',key,'scenario_planning'))
        valid.append(c)
    if violations: return [],GateResult('scenario_solver',GateStatus.FAIL,violations)
    uncovered=set(obligation_ids); selected=[]; remaining=list(valid); selected_keys=set()
    def cost(c):
        # V14 baseline: selection cost is Python-owned and uniform. AI-provided cost may be
        # retained as non-authoritative metadata, but it cannot change the selected set.
        # This makes scenario selection stable and leaves one clean selector seam for future
        # statistical/ensemble ranking of multiple candidate generators.
        return 1.0
    while uncovered:
        scored=[]
        for c in remaining:
            key=str(c['semantic_key'])
            if any(k in selected_keys for k in (c.get('incompatible_with') or [])): continue
            if any(key in (s.get('incompatible_with') or []) for s in selected): continue
            gain=len(uncovered & set(c.get('covers',[])))
            if gain<=0: continue
            scored.append((gain/cost(c),gain,-cost(c),key,c))
        if not scored: break
        scored.sort(key=lambda x:(-x[0],-x[1],-x[2],x[3]))
        chosen=dict(scored[0][4]); chosen['id']=stable_id('SCN',chosen['semantic_key']); selected.append(chosen); selected_keys.add(str(chosen['semantic_key'])); uncovered-=set(chosen.get('covers',[])); remaining=[c for c in remaining if c is not chosen]
    if uncovered: violations.append(GateViolation('SCENARIO_SOLVER_UNCOVERED_OBLIGATIONS',str(sorted(uncovered)),None,'scenario_planning','CRITICAL',{'missing':sorted(uncovered)}))
    coverage=(len(obligation_ids)-len(uncovered))/len(obligation_ids) if obligation_ids else 1.0
    return selected,GateResult('scenario_solver',GateStatus.FAIL if violations else GateStatus.PASS,violations,{'obligation_coverage':coverage,'selected_scenarios':len(selected),'candidate_scenarios':len(valid)})

def workspace_inventory_gate(workspace_inventory:Mapping[str,Any], projects:Sequence[Dict[str,Any]])->GateResult:
    """Cross-check deterministic Stage-0 baseline against the AI system map.

    A scanner must explicitly report completed=true even when it found zero items. This prevents
    "not scanned" from being indistinguishable from "scanned, none found".
    """
    violations=[]
    manifest=workspace_inventory.get('scanner_manifest') or {}
    required_scanners=('filesystem','project_markers','project_candidates','workflow_definitions','entrypoints','boundaries','concurrency')
    expected_counts={
        'filesystem': len(workspace_inventory.get('files',[]) or []),
        'project_markers': len(workspace_inventory.get('project_markers',[]) or []),
        'project_candidates': len(workspace_inventory.get('projects',[]) or []),
        'workflow_definitions': sum(1 for h in workspace_inventory.get('discovery_hints',[]) or [] if h.get('kind')=='workflow_definition'),
        'entrypoints': sum(1 for h in workspace_inventory.get('discovery_hints',[]) or [] if h.get('kind')=='entrypoint'),
        'boundaries': sum(1 for h in workspace_inventory.get('discovery_hints',[]) or [] if h.get('kind')=='boundary'),
        'concurrency': sum(1 for h in workspace_inventory.get('discovery_hints',[]) or [] if h.get('kind')=='concurrency'),
    }
    for name in required_scanners:
        m=manifest.get(name)
        if not isinstance(m,dict) or m.get('completed') is not True:
            violations.append(GateViolation('WORKSPACE_SCANNER_NOT_COMPLETED',name,None,'system_discovery','CRITICAL'))
            continue
        if m.get('count') != expected_counts[name]:
            violations.append(GateViolation('WORKSPACE_SCANNER_COUNT_MISMATCH',f"{name}: manifest={m.get('count')} actual={expected_counts[name]}",None,'system_discovery','CRITICAL'))
    expected={str(Path(p).resolve()) for p in workspace_inventory.get('project_roots',[]) or []}
    roots=[Path(r).resolve() for r in workspace_inventory.get('roots',[]) or []]
    def resolve_ai_path(raw):
        p=Path(str(raw))
        if p.is_absolute(): return str(p.resolve())
        matches=[(r/p).resolve() for r in roots if (r/p).exists()]
        if len(matches)==1: return str(matches[0])
        return str(p.resolve())
    accounted={resolve_ai_path(p.get('path')) for p in projects if isinstance(p,dict) and p.get('path')}
    expected_ids={str(Path(p['path']).resolve()):p.get('id') for p in workspace_inventory.get('projects',[]) or [] if p.get('path')}
    actual_ids={resolve_ai_path(p.get('path')):p.get('id') for p in projects if isinstance(p,dict) and p.get('path')}
    for path, expected_id in expected_ids.items():
        if path in actual_ids and actual_ids[path] != expected_id:
            violations.append(GateViolation('WORKSPACE_PROJECT_ID_DRIFT',f'{path}: expected {expected_id}, got {actual_ids[path]}',actual_ids[path],'system_discovery','CRITICAL'))
    missing=expected-accounted
    if missing: violations.append(GateViolation('WORKSPACE_PROJECT_ROOT_UNACCOUNTED',f'Project roots missing from system map: {sorted(missing)}',None,'system_discovery','CRITICAL',{'missing':sorted(missing)}))
    coverage=len(expected & accounted)/len(expected) if expected else 1.0
    return GateResult('workspace_inventory_gate',GateStatus.FAIL if violations else GateStatus.PASS,violations,{
        'deterministic_project_roots':len(expected),
        'accounted_project_roots':len(expected & accounted),
        'discovery_hints':len(workspace_inventory.get('discovery_hints',[]) or []),
        'coverage':coverage,
    })



PRIMARY_HINT_TRIGGER_TYPES={
    'http':'http','grpc':'grpc','scheduler':'scheduler','worker':'worker','consumer':'consumer','ui':'ui',
}
PRIMARY_HINT_UNIT_TYPES={
    'http':'http_entrypoint','grpc':'grpc_entrypoint','scheduler':'scheduler','worker':'worker','consumer':'consumer','ui':'ui_action',
}


def discovery_hint_closure_gate(workspace_inventory: Mapping[str, Any], analysis_units: Sequence[Dict[str, Any]], hint_dispositions: Mapping[str, Any]) -> GateResult:
    """Ensure deterministic Stage-0 hints are accounted and entrypoints keep stable leaf-unit identity."""
    hints = {h.get('id'): h for h in (workspace_inventory.get('discovery_hints') or []) if h.get('id')}
    hint_ids = set(hints); unit_ids = {u.get('id') for u in analysis_units if u.get('id')}
    lineage: Dict[str, Set[str]] = {}; units_by_id={u.get('id'):u for u in analysis_units if u.get('id')}
    for u in analysis_units:
        uid = u.get('id')
        for href in u.get('baseline_refs', []) or []:
            lineage.setdefault(href, set()).add(uid)

    base = closure_gate('discovery_hint_closure', hint_ids, hint_dispositions, 'system_discovery')
    violations = list(base.violations)
    for u in analysis_units:
        uid=u.get('id'); primary=u.get('primary_hint_ref'); refs=set(u.get('baseline_refs',[]) or [])
        if primary:
            if primary not in refs:
                violations.append(GateViolation('ANALYSIS_UNIT_PRIMARY_HINT_NOT_BASELINE','primary_hint_ref must be included in baseline_refs',uid,'system_discovery','CRITICAL'))
            h=hints.get(primary)
            if h is None:
                violations.append(GateViolation('ANALYSIS_UNIT_PRIMARY_HINT_UNKNOWN',f'Unknown primary hint: {primary}',uid,'system_discovery','CRITICAL'))
            elif h.get('kind')!='entrypoint':
                violations.append(GateViolation('ANALYSIS_UNIT_PRIMARY_HINT_NOT_ENTRYPOINT',f'Primary hint must be an entrypoint: {primary}',uid,'system_discovery','CRITICAL'))
            elif PRIMARY_HINT_UNIT_TYPES.get(str(h.get('subtype') or '').lower()) and u.get('type') != PRIMARY_HINT_UNIT_TYPES[str(h.get('subtype')).lower()]:
                violations.append(GateViolation('ANALYSIS_UNIT_PRIMARY_TYPE_MISMATCH',f'Primary hint {h.get("subtype")} requires unit type {PRIMARY_HINT_UNIT_TYPES[str(h.get("subtype")).lower()]}',uid,'system_discovery','CRITICAL'))
        required_entry_refs=[r for r in refs if r in hints and hints[r].get('required') is True and hints[r].get('kind')=='entrypoint']
        if len(required_entry_refs)>1:
            violations.append(GateViolation('ANALYSIS_UNIT_MULTIPLE_PRIMARY_ENTRYPOINTS',f'Leaf unit accounts multiple required entrypoints: {sorted(required_entry_refs)}',uid,'system_discovery','CRITICAL'))

    for hid, hint in hints.items():
        raw = hint_dispositions.get(hid)
        if raw is None: continue
        status = raw.get('status') if isinstance(raw, dict) else raw
        reason = raw.get('reason') if isinstance(raw, dict) else None
        if isinstance(raw,dict) and 'result_refs' in raw:
            violations.append(GateViolation('DISCOVERY_HINT_REDUNDANT_RESULT_REFS','result_refs is redundant; lineage is derived from analysis_units.baseline_refs',hid,'system_discovery'))
        mapped = lineage.get(hid, set()); bad = mapped - unit_ids
        if bad: violations.append(GateViolation('DISCOVERY_HINT_BAD_LINEAGE', f'Unknown analysis units: {sorted(bad)}', hid, 'system_discovery'))
        if status in {'CONFIRMED', 'REQUIRED', 'RESOLVED'} and not mapped:
            violations.append(GateViolation('DISCOVERY_HINT_NO_ANALYSIS_UNIT', 'Accepted discovery hint has no analysis-unit lineage', hid, 'system_discovery', 'CRITICAL'))
        if status in {'NON_E2E', 'EXCLUDED', 'SUPPORT_ONLY'} and not (isinstance(reason, str) and reason.strip()):
            violations.append(GateViolation('DISCOVERY_HINT_DISPOSITION_NO_REASON', f'{status} requires a concrete reason', hid, 'system_discovery'))
        if hint.get('required') is True:
            if status in {'EXCLUDED','SUPPORT_ONLY'}:
                violations.append(GateViolation('DISCOVERY_REQUIRED_HINT_DOWNGRADED', f'Required discovery hint cannot be {status}', hid, 'system_discovery', 'CRITICAL'))
            if status=='NON_E2E' and not mapped:
                violations.append(GateViolation('DISCOVERY_REQUIRED_HINT_NON_E2E_UNANALYZED','Required hint may be NON_E2E only after mapping to an analysis unit',hid,'system_discovery','CRITICAL'))
            if status in {'CONFIRMED','REQUIRED','RESOLVED','NON_E2E'} and not mapped:
                violations.append(GateViolation('DISCOVERY_REQUIRED_HINT_NO_ANALYSIS_UNIT','Required discovery hint must map to an analysis unit before final disposition',hid,'system_discovery','CRITICAL'))
            if hint.get('kind')=='entrypoint' and status in {'CONFIRMED','REQUIRED','RESOLVED'}:
                primary_units=[uid for uid in mapped if units_by_id.get(uid,{}).get('primary_hint_ref')==hid]
                if len(primary_units)!=1:
                    violations.append(GateViolation('DISCOVERY_ENTRYPOINT_PRIMARY_UNIT_COUNT',f'Required entrypoint must have exactly one primary analysis unit; got {sorted(primary_units)}',hid,'system_discovery','CRITICAL'))

    required = {hid for hid, h in hints.items() if h.get('required') is True}; accepted_required=set()
    for hid in required:
        raw=hint_dispositions.get(hid); status=raw.get('status') if isinstance(raw,dict) else raw
        if status in {'CONFIRMED','REQUIRED','RESOLVED','NON_E2E','REVIEW_REQUIRED','CONFLICT'}: accepted_required.add(hid)
    required_cov=len(accepted_required)/len(required) if required else 1.0
    metrics={**base.metrics,'required_hints':len(required),'required_hint_coverage':required_cov}
    unresolved=any(((raw.get('status') if isinstance(raw,dict) else raw) in {'REVIEW_REQUIRED','CONFLICT'}) for raw in hint_dispositions.values())
    status=GateStatus.FAIL if violations else GateStatus.REVIEW_REQUIRED if unresolved else GateStatus.PASS
    return GateResult('discovery_hint_gate',status,violations,metrics)


def anchor_closure_gate(anchor_ids: Set[str], behaviors: Sequence[Dict[str, Any]], anchor_dispositions: Mapping[str, Any]) -> GateResult:
    """Ensure Stage-1 source anchors are all explicitly handled and accepted anchors have behavior lineage."""
    behavior_ids = {b.get('id') for b in behaviors if b.get('id')}
    lineage: Dict[str, Set[str]] = {}
    violations=[]
    for b in behaviors:
        bid = b.get('id')
        for aref in b.get('anchor_refs', []) or []:
            if aref not in anchor_ids:
                violations.append(GateViolation('BEHAVIOR_UNKNOWN_ANCHOR_REF',f'Behavior references unknown anchor: {aref}',bid,'behavior_discovery','CRITICAL'))
            lineage.setdefault(aref, set()).add(bid)

    base = closure_gate('behavior_anchor_closure', anchor_ids, anchor_dispositions, 'behavior_discovery')
    violations.extend(base.violations)
    for aid in anchor_ids:
        raw = anchor_dispositions.get(aid)
        if raw is None:
            continue
        status = raw.get('status') if isinstance(raw, dict) else raw
        reason = raw.get('reason') if isinstance(raw, dict) else None
        if isinstance(raw,dict) and 'result_refs' in raw:
            violations.append(GateViolation('ANCHOR_REDUNDANT_RESULT_REFS','result_refs is redundant; lineage is derived from behavior.anchor_refs',aid,'behavior_discovery'))
        mapped = lineage.get(aid, set())
        bad = mapped - behavior_ids
        if bad:
            violations.append(GateViolation('ANCHOR_BAD_BEHAVIOR_LINEAGE', f'Unknown behaviors: {sorted(bad)}', aid, 'behavior_discovery'))
        if status in {'CONFIRMED', 'REQUIRED', 'RESOLVED'} and not mapped:
            violations.append(GateViolation('ANCHOR_NO_BEHAVIOR_LINEAGE', 'Accepted anchor has no behavior lineage', aid, 'behavior_discovery', 'CRITICAL'))
        if status in {'NON_E2E', 'EXCLUDED', 'SUPPORT_ONLY'} and not (isinstance(reason, str) and reason.strip()):
            violations.append(GateViolation('ANCHOR_DISPOSITION_NO_REASON', f'{status} requires a concrete reason', aid, 'behavior_discovery'))
    unresolved=any(((raw.get('status') if isinstance(raw,dict) else raw) in {'REVIEW_REQUIRED','CONFLICT'}) for raw in anchor_dispositions.values())
    status=GateStatus.FAIL if violations else GateStatus.REVIEW_REQUIRED if unresolved else GateStatus.PASS
    return GateResult('behavior_anchor_gate', status, violations, base.metrics)


def behavior_lineage_gate(behaviors: Sequence[Dict[str, Any]], analysis_units: Sequence[Dict[str, Any]], anchors: Sequence[Dict[str, Any]]) -> GateResult:
    """Cross-check behavior -> analysis-unit/project/anchor lineage.

    A Behavior belongs to exactly one local Analysis Unit in Stage 1. Its project and anchors
    must agree with that unit; cross-project relations are resolved later in Stage 2.
    """
    violations=[]
    units={u.get('id'):u for u in analysis_units if u.get('id')}
    anchor_by_id={a.get('id'):a for a in anchors if a.get('id')}
    for b in behaviors:
        bid=b.get('id'); uid=b.get('analysis_unit_ref'); unit=units.get(uid)
        if unit is None:
            continue
        expected_project=unit.get('project_ref')
        for aref in b.get('anchor_refs',[]) or []:
            anchor=anchor_by_id.get(aref)
            if anchor is None:
                violations.append(GateViolation('BEHAVIOR_UNKNOWN_ANCHOR_REF',f'Unknown anchor: {aref}',bid,'behavior_discovery','CRITICAL'))
                continue
            if anchor.get('analysis_unit_ref') != uid:
                violations.append(GateViolation('BEHAVIOR_ANCHOR_UNIT_MISMATCH',f'Anchor {aref} belongs to {anchor.get("analysis_unit_ref")} not {uid}',bid,'behavior_discovery','CRITICAL'))
            if anchor.get('project_ref') != expected_project:
                violations.append(GateViolation('BEHAVIOR_ANCHOR_PROJECT_MISMATCH',f'Anchor {aref} project {anchor.get("project_ref")} != {expected_project}',bid,'behavior_discovery','CRITICAL'))
    return GateResult('behavior_lineage_gate',GateStatus.FAIL if violations else GateStatus.PASS,violations)


def quality_results_gate(quality_results: Mapping[str, Any], required_stages: Sequence[str], quality_validator, stage_fingerprints: Mapping[str,str]|None=None) -> GateResult:
    """Require auditable Grill + Review artifacts for each configured stage.

    Python gates are recomputed independently; this gate only proves the semantic challenger/reviewer
    steps occurred and passed their contracts.
    """
    violations=[]; checked=0; stage_fingerprints=dict(stage_fingerprints or {})
    unknown=set(quality_results)-set(required_stages)
    if unknown:
        violations.append(GateViolation('QUALITY_UNKNOWN_STAGE',f'Unknown quality stages: {sorted(unknown)}',None,'quality'))
    for stage in required_stages:
        raw=quality_results.get(stage)
        if not isinstance(raw,dict):
            violations.append(GateViolation('QUALITY_STAGE_MISSING',f'Missing quality artifacts for {stage}',stage,'quality','CRITICAL')); continue
        expected_fp=stage_fingerprints.get(stage)
        grills=raw.get('grill')
        if not isinstance(grills,list) or not grills:
            violations.append(GateViolation('QUALITY_GRILL_MISSING',f'{stage} requires at least one Grill result',stage,'quality','CRITICAL'))
        else:
            for i,g in enumerate(grills):
                if not isinstance(g,dict):
                    violations.append(GateViolation('QUALITY_GRILL_BAD_TYPE',f'{stage}.grill[{i}] must be object',stage,'quality')); continue
                gr=quality_validator(g,'grill'); checked+=1
                violations.extend(gr.violations)
                if expected_fp and g.get('artifact_fingerprint')!=expected_fp:
                    violations.append(GateViolation('QUALITY_ARTIFACT_FINGERPRINT_MISMATCH',f'{stage}.grill[{i}] was not run against the final stage artifact',stage,'quality','CRITICAL'))
                if isinstance(g.get('issues'),list) and g.get('issues'):
                    violations.append(GateViolation('QUALITY_GRILL_UNRESOLVED_ISSUES',f'{stage}.grill[{i}] still reports {len(g.get("issues"))} issue(s) on the final artifact',stage,'quality','CRITICAL'))
        review=raw.get('review')
        if not isinstance(review,dict):
            violations.append(GateViolation('QUALITY_REVIEW_MISSING',f'{stage} requires Review result',stage,'quality','CRITICAL'))
        else:
            rr=quality_validator(review,'review'); checked+=1
            violations.extend(rr.violations)
            if expected_fp and review.get('artifact_fingerprint')!=expected_fp:
                violations.append(GateViolation('QUALITY_ARTIFACT_FINGERPRINT_MISMATCH',f'{stage}.review was not run against the final stage artifact',stage,'quality','CRITICAL'))
            if review.get('result')!='PASS':
                violations.append(GateViolation('QUALITY_REVIEW_NOT_PASS',f'{stage} review result must be PASS before final validation',stage,'quality','CRITICAL'))
    return GateResult('quality_results_gate',GateStatus.FAIL if violations else GateStatus.PASS,violations,{'required_stages':len(required_stages),'validated_quality_artifacts':checked})

def analysis_scope_gate(analysis_units: Sequence[Dict[str, Any]], analysis_scopes: Mapping[str, Any], readonly_roots: Sequence[Path], *, baseline_sources: Mapping[str, str] | None=None, project_paths: Mapping[str, str] | None=None) -> GateResult:
    """Validate exact files used for Stage-1 and prove baseline/seed sources were actually read."""
    violations=[]; units={u.get('id'):u for u in analysis_units if u.get('id')}; roots=[Path(r).resolve() for r in readonly_roots]
    baseline_sources=dict(baseline_sources or {}); project_paths={k:str(v) for k,v in dict(project_paths or {}).items()}
    unknown=set(analysis_scopes)-set(units)
    if unknown: violations.append(GateViolation('ANALYSIS_SCOPE_UNKNOWN_UNIT',f'Unknown units: {sorted(unknown)}',None,'behavior_discovery'))

    def resolve_file(raw, project_ref=None):
        p=Path(str(raw))
        candidates=[p] if p.is_absolute() else [r/p for r in roots]
        if not p.is_absolute() and project_ref in project_paths:
            candidates.append(Path(project_paths[project_ref]).resolve()/p)
        existing=[]
        for x in candidates:
            if x.exists() and x.is_file():
                rx=x.resolve()
                if rx not in existing: existing.append(rx)
        return existing[0] if len(existing)==1 else None

    resolved={}
    for uid,u in units.items():
        status=u.get('status'); raw_files=analysis_scopes.get(uid)
        if status=='READY' and (not isinstance(raw_files,list) or not raw_files):
            violations.append(GateViolation('ANALYSIS_SCOPE_MISSING',f'Confirmed/READY unit has no analyzed file scope: {uid}',uid,'behavior_discovery','CRITICAL')); continue
        if raw_files is None: continue
        if not isinstance(raw_files,list): violations.append(GateViolation('ANALYSIS_SCOPE_BAD_TYPE','Analysis scope must be a list of files',uid,'behavior_discovery')); continue
        seen=[]
        for raw in raw_files:
            p=resolve_file(raw,u.get('project_ref'))
            if p is None: violations.append(GateViolation('ANALYSIS_SCOPE_FILE_NOT_FOUND_OR_AMBIGUOUS',str(raw),uid,'behavior_discovery','CRITICAL')); continue
            if roots and not any(p.is_relative_to(r) for r in roots): violations.append(GateViolation('ANALYSIS_SCOPE_OUTSIDE_INPUT_ROOT',str(p),uid,'behavior_discovery','CRITICAL')); continue
            seen.append(str(p))
        seen_set=set(seen); resolved[uid]=sorted(seen_set)
        if status=='READY':
            required_sources=set()
            for ref in u.get('baseline_refs',[]) or []:
                raw_src=baseline_sources.get(ref)
                if raw_src:
                    rp=resolve_file(raw_src,u.get('project_ref'))
                    if rp is not None: required_sources.add(str(rp))
            seed=u.get('seed') if isinstance(u.get('seed'),dict) else {}
            for key in ('file','path','source_file'):
                raw_seed=seed.get(key)
                if raw_seed:
                    rp=resolve_file(raw_seed,u.get('project_ref'))
                    if rp is not None: required_sources.add(str(rp))
            missing=required_sources-seen_set
            if missing:
                violations.append(GateViolation('ANALYSIS_SCOPE_BASELINE_SOURCE_MISSING',f'Analysis scope omitted baseline/seed source files: {sorted(missing)}',uid,'behavior_discovery','CRITICAL',{'missing':sorted(missing)}))
            symbol=seed.get('symbol')
            if isinstance(symbol,str) and symbol.strip() and seen_set:
                token=symbol.strip().replace('::','.').split('.')[-1]
                found=False
                for raw_path in seen_set:
                    try:
                        if token in Path(raw_path).read_text(encoding='utf-8',errors='ignore'):
                            found=True; break
                    except OSError:
                        pass
                if not found:
                    violations.append(GateViolation('ANALYSIS_SCOPE_SEED_SYMBOL_MISSING',f'Seed symbol not found in analyzed scope: {symbol}',uid,'behavior_discovery','CRITICAL'))
    return GateResult('analysis_scope_gate',GateStatus.FAIL if violations else GateStatus.PASS,violations,{'scoped_units':len(resolved),'scoped_files':sum(len(x) for x in resolved.values())})



def behavior_primary_trigger_gate(behaviors: Sequence[Dict[str, Any]], analysis_units: Sequence[Dict[str, Any]], discovery_hints: Sequence[Dict[str, Any]]) -> GateResult:
    """Bind each primary leaf Analysis Unit to the same concrete entrypoint in Stage-1 Behavior."""
    violations=[]; hints={h.get('id'):h for h in discovery_hints if h.get('id')}; by_unit={b.get('analysis_unit_ref'):b for b in behaviors if b.get('analysis_unit_ref')}
    for u in analysis_units:
        primary=u.get('primary_hint_ref')
        if not primary: continue
        uid=u.get('id'); h=hints.get(primary); b=by_unit.get(uid)
        if h is None or b is None: continue
        subtype=str(h.get('subtype') or '').lower(); expected=PRIMARY_HINT_TRIGGER_TYPES.get(subtype)
        trigger=b.get('trigger') if isinstance(b.get('trigger'),dict) else {}
        if expected and trigger.get('type') != expected:
            violations.append(GateViolation('BEHAVIOR_PRIMARY_TRIGGER_TYPE_MISMATCH',f'Primary hint {subtype} requires trigger.type={expected}, got {trigger.get("type")}',b.get('id'),'behavior_discovery','CRITICAL'))
        if trigger.get('source_hint_ref') != primary:
            violations.append(GateViolation('BEHAVIOR_PRIMARY_HINT_LINEAGE_MISSING',f'trigger.source_hint_ref must equal {primary}',b.get('id'),'behavior_discovery','CRITICAL'))
    return GateResult('behavior_primary_trigger_gate',GateStatus.FAIL if violations else GateStatus.PASS,violations)


def workspace_project_exactness_gate(workspace_inventory: Mapping[str, Any], projects: Sequence[Dict[str, Any]], readonly_roots: Sequence[Path]) -> GateResult:
    """Require the persisted Stage-0 Project universe to equal the deterministic scanner universe.

    `workspace_inventory_gate()` historically guaranteed no deterministic project root was omitted.
    This stricter V11 gate also rejects invented/duplicate project roots and IDs so AI cannot expand
    or relabel the authoritative workspace denominator.
    """
    violations=[]; roots=[Path(r).resolve() for r in readonly_roots]
    expected_by_path={str(Path(p['path']).resolve()):str(p.get('id')) for p in workspace_inventory.get('projects',[]) or [] if p.get('path') and p.get('id')}
    expected_paths=set(expected_by_path); expected_ids=set(expected_by_path.values())
    actual_by_path={}; actual_ids=set()
    for p in projects:
        if not isinstance(p,Mapping):
            violations.append(GateViolation('WORKSPACE_PROJECT_BAD_TYPE','Project entry must be object',None,'system_discovery','CRITICAL')); continue
        raw=p.get('path'); pid=str(p.get('id') or '')
        if not raw or not pid:
            violations.append(GateViolation('WORKSPACE_PROJECT_INCOMPLETE','Project requires path and deterministic id',pid or None,'system_discovery','CRITICAL')); continue
        path=Path(str(raw))
        if not path.is_absolute():
            matches=[(r/path).resolve() for r in roots if (r/path).exists()]
            path=matches[0] if len(matches)==1 else path.resolve()
        else: path=path.resolve()
        sp=str(path)
        if sp in actual_by_path:
            violations.append(GateViolation('WORKSPACE_DUPLICATE_PROJECT_PATH',sp,pid,'system_discovery','CRITICAL'))
        actual_by_path[sp]=pid
        if pid in actual_ids:
            violations.append(GateViolation('WORKSPACE_DUPLICATE_PROJECT_ID',pid,pid,'system_discovery','CRITICAL'))
        actual_ids.add(pid)
        if not path.exists() or not path.is_dir():
            violations.append(GateViolation('WORKSPACE_PROJECT_PATH_INVALID',sp,pid,'system_discovery','CRITICAL'))
        elif roots and not any(path.is_relative_to(r) for r in roots):
            violations.append(GateViolation('WORKSPACE_PROJECT_OUTSIDE_ROOT',sp,pid,'system_discovery','CRITICAL'))
    unknown_paths=set(actual_by_path)-expected_paths
    if unknown_paths:
        violations.append(GateViolation('WORKSPACE_INVENTED_PROJECT_ROOT',str(sorted(unknown_paths)),None,'system_discovery','CRITICAL'))
    missing_paths=expected_paths-set(actual_by_path)
    if missing_paths:
        violations.append(GateViolation('WORKSPACE_PROJECT_ROOT_MISSING',str(sorted(missing_paths)),None,'system_discovery','CRITICAL'))
    unknown_ids=actual_ids-expected_ids
    if unknown_ids:
        violations.append(GateViolation('WORKSPACE_INVENTED_PROJECT_ID',str(sorted(unknown_ids)),None,'system_discovery','CRITICAL'))
    for path,pid in actual_by_path.items():
        expected=expected_by_path.get(path)
        if expected is not None and pid!=expected:
            violations.append(GateViolation('WORKSPACE_PROJECT_ID_DRIFT',f'{path}: expected {expected}, got {pid}',pid,'system_discovery','CRITICAL'))
    return GateResult('workspace_project_exactness_gate',GateStatus.FAIL if violations else GateStatus.PASS,violations,{
        'expected_projects':len(expected_paths),'persisted_projects':len(actual_by_path)
    })
