#!/usr/bin/env python3
import json, sys
from pathlib import Path

args = sys.argv[1:]
root = Path.cwd()
state_dir = Path(__import__('os').environ.get('FLAKY_STATE_DIR', root))
state_dir.mkdir(parents=True, exist_ok=True)
is_qwen = '-p' in args
prompt_arg = args[args.index('-p') + 1] if is_qwen else args[-1]
stdin_prompt = sys.stdin.read() if is_qwen else ""
prompt = "\n".join(part for part in (stdin_prompt, prompt_arg) if part).strip()
session = 'retry-session-001'

if 'independent plan editor' in prompt:
    phase, answer = 'plan_refine', {'tasks':[{'title':'Create marker','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists']}]}
elif 'Plan only the remaining work' in prompt:
    phase, answer = 'plan', {'tasks':[{'title':'Create marker','description':'create done.txt','deliverable':'done.txt exists','acceptance_criteria':['done.txt exists']}]}
elif 'plan quality judge' in prompt:
    phase = 'plan_judge'
    n = max(1, prompt.count('\"title\"'))
    answer = {'task_checks':[{'index':i,'produces_change':True,'properly_sized':True,'verifiable':True,'issues':[]} for i in range(1,n+1)],'coverage_complete':True,'dependency_order_ok':True,'no_overlap':True,'plan_issues':[]}
elif 'Execute only the current task' in prompt or 'Complete only the current TODO' in prompt:
    phase, answer = 'execute', 'created done.txt'
elif 'review only' in prompt.lower():
    phase, answer = 'review', {'completed':True,'reason':'checked','missing_items':[]}
elif 'fresh independent session' in prompt:
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
