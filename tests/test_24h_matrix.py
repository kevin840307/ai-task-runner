from __future__ import annotations
import json, sys, textwrap
from pathlib import Path
import pytest
from runner.api import RunRequest, run
from runner.config.defaults import DEFAULT_MAX_CYCLES
ROOT=Path(__file__).resolve().parents[1]
def cmd(): return f'"{sys.executable}" "{ROOT / "tests/scenario_agent.py"}"'
def records(sd):
 p=sd/'prompt-log.jsonl'; return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
def stages(project):
 p=project/'.ai-task-runner'/'log.txt'
 return [json.loads(x)['stage'] for x in p.read_text(encoding='utf-8').splitlines() if json.loads(x).get('type')=='runner.stage' and json.loads(x).get('action')=='start']
def base(tmp_path, monkeypatch, scenario, validator='ai', **kw):
 sd=tmp_path.parent/f'{tmp_path.name}-{scenario}-state'; monkeypatch.setenv('SCENARIO',scenario); monkeypatch.setenv('SCENARIO_STATE_DIR',str(sd))
 req=RunRequest(goal='Create requested result',project_root=str(tmp_path),validator=validator,backend='qwen',command=cmd(),max_attempts=kw.pop('max_attempts',2),max_cycles=kw.pop('max_cycles',DEFAULT_MAX_CYCLES),retry_delay=0,retry_wait=0,retry_max_wait=0,api_wait_timeout=10,agent_idle_after_change_timeout=0,**kw)
 r=run(req); return r,records(sd)
def validator(path):
 path.write_text(textwrap.dedent('''import argparse\nfrom pathlib import Path\np=argparse.ArgumentParser(); p.add_argument("--project-root"); p.add_argument("--state-file"); a,_=p.parse_known_args()\nraise SystemExit(0 if (Path(a.project_root)/"done.txt").exists() else 5)\n'''))
def mixed_project(root):
 root.mkdir(); (root/'prompt.md').write_text('Create requested result\n',encoding='utf-8'); (root/'ai.md').write_text('Independently confirm the requested result.\n',encoding='utf-8'); validator(root/'validator.py')
def script_stages(project,index):
 p=project/'.ai-task-runner'/'script'/f'{index:03d}'/'log.txt'
 return [json.loads(x)['stage'] for x in p.read_text(encoding='utf-8').splitlines() if json.loads(x).get('type')=='runner.stage' and json.loads(x).get('action')=='start']

def test_ai_validation(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'happy_path'); flow=stages(tmp_path); assert r.completed; assert [x['stage'] for x in recs][-1]=='validator'; assert 'validate_ai' in flow and 'validate_file' not in flow
def test_python_validation(tmp_path,monkeypatch):
 v=tmp_path/'validator.py'; validator(v); r,recs=base(tmp_path,monkeypatch,'happy_path',str(v)); flow=stages(tmp_path); assert r.completed; assert 'validator' not in [x['stage'] for x in recs]; assert 'validate_file' in flow and 'validate_ai' not in flow
def test_mixed_validation(tmp_path,monkeypatch):
 v=tmp_path/'validator.py'; validator(v); r,recs=base(tmp_path,monkeypatch,'happy_path',str(v),ai_validator_prompt='independent check'); flow=stages(tmp_path); assert r.completed; assert 'validator' in [x['stage'] for x in recs]; assert 'validate_file' in flow and 'validate_ai' in flow
def test_file_protection(tmp_path,monkeypatch):
 p=tmp_path/'protected.txt'; p.write_text('original'); monkeypatch.setenv('PROTECTED_PATH',str(p)); r,recs=base(tmp_path,monkeypatch,'protected_retry',protect_files=[str(p)]); assert r.completed; assert p.read_text()=='original'; assert sum(x['stage']=='execute' for x in recs)>=2
def test_loop_recovery(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'loop_detection',max_attempts=1); assert r.completed; ex=[x for x in recs if x['stage']=='execute']; assert len(ex)>=2; assert ex[1]['resumed']
def test_multi_retry(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'execution_model_error',max_attempts=2); assert r.completed; ex=[x for x in recs if x['stage']=='execute']; assert len(ex)>=4; assert any(not x['resumed'] for x in ex[1:])
def test_review_repair(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'review_retry'); assert r.completed; assert sum(x['stage']=='review' for x in recs)>=2; assert sum(x['stage']=='execute' for x in recs)>=2
def test_ai_replan(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'ai_replan'); assert r.completed; assert sum(x['stage']=='validator' for x in recs)>=2; assert r.states[0]['cycle']>=2
def test_default_unlimited_cycles_continue_past_four_failures(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'ai_replan_many'); assert r.completed; assert sum(x['stage']=='validator' for x in recs)>=5; assert r.states[0]['cycle']>=5
def test_yaml_default_unlimited_cycles_continue_past_four_failures(tmp_path,monkeypatch):
 sd=tmp_path.parent/f'{tmp_path.name}-yaml-many-state'; monkeypatch.setenv('SCENARIO','ai_replan_many'); monkeypatch.setenv('SCENARIO_STATE_DIR',str(sd))
 script=tmp_path/'tasks.yaml'; script.write_text('- prompt: Create requested result\n  validator: ai\n',encoding='utf-8')
 r=run(RunRequest(project_root=str(tmp_path),script=str(script),backend='qwen',command=cmd(),retry_delay=0,retry_wait=0,retry_max_wait=0,api_wait_timeout=10,agent_idle_after_change_timeout=0))
 assert r.completed; assert r.states[0]['cycle']>=5
def test_yaml_mixed_reliability_gate_survives_repeated_final_ai_replans(tmp_path,monkeypatch):
 sd=tmp_path.parent/f'{tmp_path.name}-yaml-mixed-reliability-state'; monkeypatch.setenv('SCENARIO','ai_replan_many_per_project'); monkeypatch.setenv('SCENARIO_STATE_DIR',str(sd))
 for name in ('one','two'): mixed_project(tmp_path/name)
 one_validator=str(tmp_path/'one'/'validator.py').replace("'","''"); two_validator=str(tmp_path/'two'/'validator.py').replace("'","''")
 script=tmp_path/'tasks.yaml'; script.write_text(textwrap.dedent(f'''\
 - goal_file: one/prompt.md
   project_root: one
   validator: '{one_validator}'
   ai_validator_prompt_file: one/ai.md
   ai_validator_count: 3
   ai_validator_required_passes: 3
 - goal_file: two/prompt.md
   project_root: two
   validator: '{two_validator}'
   ai_validator_prompt_file: two/ai.md
   ai_validator_count: 3
   ai_validator_required_passes: 3
 '''),encoding='utf-8')
 r=run(RunRequest(project_root=str(tmp_path),script=str(script),backend='qwen',command=cmd(),retry_delay=0,retry_wait=0,retry_max_wait=0,api_wait_timeout=10,agent_idle_after_change_timeout=0))
 assert r.completed and len(r.states)==2
 assert [state['cycle'] for state in r.states]==[3,3]
 assert all('validate_file' in script_stages(tmp_path/name,index) and script_stages(tmp_path/name,index).count('validate_ai')==3 for index,name in enumerate(('one','two'),1))
 recs=records(sd); votes=[x for x in recs if x['stage']=='validator']
 assert len(votes)==18
 assert all(not x['resumed'] for x in votes)
def test_stagnation_repair(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'stagnation'); assert r.completed; assert sum(x['stage']=='review' for x in recs)>=4
def test_api_503_recovers(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'api_503',max_attempts=1); assert r.completed; assert sum(x['stage']=='execute' for x in recs)>=4

def test_readonly_review_validator_restores_mutation(tmp_path,monkeypatch):
 r,recs=base(tmp_path,monkeypatch,'readonly',max_attempts=2)
 assert r.completed
 assert not (tmp_path/'review_mutation.txt').exists()
 assert not (tmp_path/'validator_mutation.txt').exists()
 assert sum(x['stage']=='review' for x in recs)>=2
 assert sum(x['stage']=='validator' for x in recs)>=2

def test_plan_only_then_resume(tmp_path,monkeypatch):
 sd=tmp_path.parent/f'{tmp_path.name}-resume-state'; monkeypatch.setenv('SCENARIO','happy_path'); monkeypatch.setenv('SCENARIO_STATE_DIR',str(sd))
 first=run(RunRequest(goal='Create requested result',project_root=str(tmp_path),validator='ai',backend='qwen',command=cmd(),plan_only=True,max_attempts=2,retry_delay=0,retry_wait=0,retry_max_wait=0,api_wait_timeout=10,agent_idle_after_change_timeout=0))
 assert not first.completed
 assert first.states and first.states[0]['tasks'] and first.states[0]['current']==0
 before=records(sd)
 assert all(x['stage'] not in {'execute','review','validator'} for x in before)
 second=run(RunRequest(project_root=str(tmp_path),validator='ai',backend='qwen',command=cmd(),resume=True,max_attempts=2,retry_delay=0,retry_wait=0,retry_max_wait=0,api_wait_timeout=10,agent_idle_after_change_timeout=0))
 assert second.completed
 after=records(sd)[len(before):]
 assert after and after[0]['stage']=='execute'
 assert after[0]['resumed'] is True
