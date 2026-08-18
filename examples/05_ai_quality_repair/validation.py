#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

def call(root,cfg,env,service):
    return subprocess.run([sys.executable,str(root/'route_config.py'),'--config',str(cfg),'--env',env,'--service',service],cwd=root,text=True,capture_output=True,timeout=20)
def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    try:
        assert (root/'route_config.py').is_file(),'missing route_config.py'
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'routes.json'; cfg.write_text(json.dumps({'environments':{'DEV':{'api':'http://dev.local/api'},'PROD':{'api':'https://prod.local/api'}}}),encoding='utf-8')
            assert call(root,cfg,'DEV','api').stdout.strip()=='http://dev.local/api','DEV/api output mismatch'
            assert call(root,cfg,'PROD','api').stdout.strip()=='https://prod.local/api','PROD/api output mismatch'
            assert call(root,cfg,'DEV','missing').returncode!=0,'missing service must fail'
        print('VALIDATION_PASSED'); return 0
    except Exception as e:
        print('VALIDATION_FAILED'); print(f'[E001] {e}'); return 1
if __name__=='__main__': raise SystemExit(main())
