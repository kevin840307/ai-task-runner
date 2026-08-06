#!/usr/bin/env python3
import json, sys
from pathlib import Path
args=sys.argv[1:]
root=Path.cwd(); session='test-session-001'
is_qwen='-p' in args
prompt_arg = args[args.index('-p')+1] if is_qwen else args[-1]
stdin_prompt = sys.stdin.read() if is_qwen else ""
prompt = "\n".join(part for part in (stdin_prompt, prompt_arg) if part).strip()
is_validator = 'fresh independent session' in prompt
if is_validator:
    assert '--resume' not in args and '--session' not in args
    session = 'validator-session-001'
elif is_qwen and '--resume' in args:
    assert args[args.index('--resume')+1] == session
elif not is_qwen and '--session' in args:
    assert args[args.index('--session')+1] == session
if 'Plan only the remaining work' in prompt or 'independent plan editor' in prompt:
    answer=json.dumps({'tasks':[{'title':'Create marker','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists']}]})
elif 'plan quality judge' in prompt:
    count = max(1, prompt.count('\"title\"'))
    answer = json.dumps({'task_checks':[{'index':i,'produces_change':True,'properly_sized':True,'verifiable':True,'issues':[]} for i in range(1,count+1)],'coverage_complete':True,'dependency_order_ok':True,'no_overlap':True,'plan_issues':[]})
elif 'Execute only the current task' in prompt or 'Complete only the current TODO' in prompt:
    (root/'done.txt').write_text('done'); answer='created done.txt'
elif 'review only' in prompt.lower():
    answer=json.dumps({'completed':(root/'done.txt').exists(),'reason':'checked','missing_items':[]})
elif 'fresh independent session' in prompt:
    answer=json.dumps({'passed':(root/'done.txt').exists(),'reason':'independent check','missing_items':[]})
else:
    raise SystemExit(2)
if is_qwen:
    print(json.dumps([{'type':'system','subtype':'session_start','session_id':session},{'type':'result','subtype':'success','session_id':session,'result':answer}]))
else:
    print(json.dumps({'type':'session','sessionID':session}))
    print(json.dumps({'type':'message','part':{'type':'text','text':answer}}))
