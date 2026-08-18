#!/usr/bin/env python3
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

def run(root, text):
    with tempfile.TemporaryDirectory() as d:
        d=Path(d); src=d/'in.txt'; out=d/'nested'/'stats.json'; src.write_text(text,encoding='utf-8')
        r=subprocess.run([sys.executable,str(root/'text_stats.py'),'--input',str(src),'--output',str(out)],cwd=root,text=True,capture_output=True,timeout=20)
        assert r.returncode==0, f'command failed: {r.stdout}{r.stderr}'
        assert out.is_file(), 'output JSON was not created'
        return json.loads(out.read_text(encoding='utf-8'))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--project-root',required=True); p.add_argument('--state-file'); a,_=p.parse_known_args(); root=Path(a.project_root).resolve()
    try:
        script=root/'text_stats.py'; assert script.is_file(),'missing text_stats.py'
        for text in ['alpha beta\n\ngamma\n','你好 world\nsecond line','']:
            lines=text.splitlines(); expected={'lines':len(lines),'words':len(text.split()),'characters':len(text),'non_empty_lines':sum(bool(x.strip()) for x in lines)}
            actual=run(root,text); assert actual==expected,f'wrong stats for {text!r}: expected={expected}, actual={actual}'
        missing=subprocess.run([sys.executable,str(script),'--input',str(root/'does-not-exist.txt'),'--output',str(root/'unused.json')],cwd=root,text=True,capture_output=True,timeout=20)
        assert missing.returncode!=0,'missing input must return non-zero'
        print('VALIDATION_PASSED'); return 0
    except Exception as e:
        print('VALIDATION_FAILED'); print(f'[E001] {e}'); return 1
if __name__=='__main__': raise SystemExit(main())
