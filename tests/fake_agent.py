#!/usr/bin/env python3
import json, sys
from pathlib import Path

from fake_agent_io import prompt_stage, read_prompt

args=sys.argv[1:]
root=Path.cwd(); session='test-session-001'
is_qwen, prompt = read_prompt(args)
stage = prompt_stage(prompt)
is_validator = stage == "validator"
if is_validator:
    assert '--resume' not in args and '--session' not in args
    session = 'validator-session-001'
elif is_qwen and '--resume' in args:
    assert args[args.index('--resume')+1] == session
elif not is_qwen and '--session' in args:
    assert args[args.index('--session')+1] == session
if stage == "plan_understand":
    answer='relevant project evidence gathered'
elif stage in {"plan_finalize", "plan_refine"}:
    count = 2 if 'repair plan' in prompt.lower() or 'repair planning' in prompt.lower() else 6
    answer=json.dumps({'tasks':[{'title':f'Create marker {i}','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists']} for i in range(1,count+1)]})
elif stage == "plan_judge":
    count = max(1, prompt.count('\"title\"'))
    answer = json.dumps({"accepted": True, "issues": []})
elif stage == "execute":
    (root/'done.txt').write_text('done'); answer='created done.txt'
elif stage == "review":
    answer=json.dumps({'completed':(root/'done.txt').exists(),'reason':'checked','missing_items':[]})
elif stage == "validator":
    answer=json.dumps({'passed':(root/'done.txt').exists(),'reason':'independent check','missing_items':[]})
else:
    raise SystemExit(2)
if is_qwen:
    print(json.dumps([{'type':'system','subtype':'session_start','session_id':session},{'type':'result','subtype':'success','session_id':session,'result':answer}]))
else:
    print(json.dumps({'type':'session','sessionID':session}))
    print(json.dumps({'type':'message','part':{'type':'text','text':answer}}))
