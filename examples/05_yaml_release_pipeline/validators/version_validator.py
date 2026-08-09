#!/usr/bin/env python3
import argparse, json, subprocess, sys
from pathlib import Path
from validator_interface import ValidatorReport, run_validation

def validate(root: Path)->None:
    version=json.loads((root/'release_notes.json').read_text(encoding='utf-8'))['version']
    path=root/'VERSION'; actual=path.read_text(encoding='utf-8').strip() if path.is_file() else '(missing)'; assert actual==version, f'VERSION mismatch: expected={version!r}, actual={actual!r}'
    r=subprocess.run([sys.executable,'app.py','--version'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert r.returncode==0 and r.stdout.strip()==version, 'app.py --version failed:\n'+r.stdout
    r=subprocess.run([sys.executable,'app.py'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    assert r.returncode==0, 'normal app.py execution failed:\n'+r.stdout

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file',required=True); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    return run_validation(ValidatorReport(root,'release-version'), lambda: validate(root))
if __name__=='__main__': raise SystemExit(main())
