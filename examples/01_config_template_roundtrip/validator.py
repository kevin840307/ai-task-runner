#!/usr/bin/env python3
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a, _ = p.parse_known_args()
root = Path(a.project_root)
source = root / "input" / "configs"
template = root / "template" / "config.ini.j2"
values = root / "values.yaml"
renderer = root / "render.py"
out = root / "output" / "configs"

missing = [str(x.relative_to(root)) for x in (template, values, renderer) if not x.is_file()]
if missing:
    print("Missing required files: " + ", ".join(missing))
    raise SystemExit(1)

value_lines = [line for line in values.read_text(encoding="utf-8").splitlines() if line.strip()]
if len(value_lines) > 24:
    print(f"values.yaml has {len(value_lines)} non-empty lines; maximum is 24")
    raise SystemExit(1)
if any(len(line) > 160 for line in value_lines):
    print("values.yaml contains a line longer than 160 characters")
    raise SystemExit(1)
if values.stat().st_size > 2400:
    print("values.yaml is too large to be considered compact")
    raise SystemExit(1)
if "{{" not in template.read_text(encoding="utf-8"):
    print("template/config.ini.j2 does not contain template placeholders")
    raise SystemExit(1)

if out.parent.exists():
    shutil.rmtree(out.parent)
r = subprocess.run([sys.executable, str(renderer)], cwd=root, text=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if r.returncode != 0:
    print(r.stdout)
    raise SystemExit(r.returncode)

expected = sorted(p.relative_to(source) for p in source.rglob("*") if p.is_file())
actual = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file()) if out.exists() else []
if actual != expected:
    print(f"Output files differ. expected={expected}, actual={actual}")
    raise SystemExit(1)
for rel in expected:
    if (source / rel).read_bytes() != (out / rel).read_bytes():
        print(f"Byte comparison failed: {rel}")
        raise SystemExit(1)
print(f"PASS: {len(expected)} configs round-tripped; values lines={len(value_lines)}")
