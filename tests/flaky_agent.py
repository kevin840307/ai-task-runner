#!/usr/bin/env python3
import json, sys
from pathlib import Path

from fake_agent_io import prompt_stage, read_prompt

args = sys.argv[1:]
root = Path.cwd()
state_dir = Path(__import__('os').environ.get('FLAKY_STATE_DIR', root))
state_dir.mkdir(parents=True, exist_ok=True)
is_qwen, prompt = read_prompt(args)
stage = prompt_stage(prompt)
session = 'retry-session-001'

if stage == 'plan_refine':
    phase, answer = 'plan_refine', {'tasks':[{'title':'Create marker','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists'],'steps':['execute','review']}]}
elif stage == 'plan_finalize':
    phase, answer = 'plan', {'tasks':[{'title':'Create marker','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists'],'steps':['execute','review']}]}
elif stage == 'plan_judge':
    phase = 'plan_judge'
    n = max(1, prompt.count('\"title\"'))
    answer = {"accepted": True, "issues": []}
elif stage == 'execute':
    phase, answer = 'execute', 'created done.txt'
elif stage == 'review':
    phase, answer = 'review', {'completed':True,'reason':'checked','missing_items':[]}
elif stage == 'validator':
    phase, answer = 'validator', {'passed':True,'reason':'checked','missing_items':[]}
    session = 'retry-validator-session-001'
else:
    raise SystemExit(2)

counter = state_dir / f'.{phase}.count'
count = int(counter.read_text() or '0') if counter.exists() else 0
counter.write_text(str(count + 1))
if count == 0 and phase != 'plan_refine':
    print('temporary model failure')
    raise SystemExit(7)

if phase == 'execute':
    (root / 'done.txt').write_text('done')

text = json.dumps(answer) if isinstance(answer, dict) else answer
if is_qwen:
    print(json.dumps([{'type':'system','subtype':'session_start','session_id':session},
                      {'type':'result','subtype':'success','session_id':session,'result':text}]))
else:
    print(json.dumps({'type':'session','sessionID':session}))
    print(json.dumps({'type':'message','part':{'type':'text','text':text}}))
