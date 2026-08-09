#!/usr/bin/env python3
import json, sys
from pathlib import Path
args=sys.argv[1:]
root=Path.cwd(); session='test-session-001'
is_qwen='--output-format' in args and 'stream-json' in args
prompt = sys.stdin.read() if is_qwen else args[-1]
is_validator = 'fresh independent session' in prompt
if is_validator:
    assert '--resume' not in args and '--session' not in args
    session = 'validator-session-001'
elif is_qwen and '--resume' in args:
    assert args[args.index('--resume')+1] == session
elif not is_qwen and '--session' in args:
    assert args[args.index('--session')+1] == session
if 'dedicated project-understanding turn' in prompt:
    answer='relevant project evidence gathered'
elif 'Create the implementation plan now' in prompt or 'Plan only the remaining work' in prompt or 'Continue the existing planning work' in prompt:
    count = 2 if 'repair plan' in prompt.lower() or 'repair planning' in prompt.lower() else 6
    answer=json.dumps({'tasks':[{'title':f'Create marker {i}','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists']} for i in range(1,count+1)]})
elif 'plan quality judge' in prompt:
    count = max(1, prompt.count('\"title\"'))
    answer = json.dumps({"accepted": True, "issues": []})
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
