#!/usr/bin/env python3
"""Build the React Flow Workflow Studio into static UI assets."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ui" / "studio-src"
OUTPUT = ROOT / "ui" / "static" / "workflow-studio-app"


def main() -> int:
    npm = shutil.which("npm")
    if not npm:
        print("npm is required only to build Workflow Studio.", file=sys.stderr)
        return 2

    lockfile = SOURCE / "package-lock.json"
    install = ["npm", "ci"] if lockfile.is_file() else ["npm", "install"]
    subprocess.run(install, cwd=SOURCE, check=True)
    subprocess.run(["npm", "run", "build"], cwd=SOURCE, check=True)

    index = OUTPUT / "index.html"
    assets = OUTPUT / "assets"
    if not index.is_file() or not assets.is_dir():
        print("Workflow Studio build did not produce expected static assets.", file=sys.stderr)
        return 3

    text = index.read_text(encoding="utf-8")
    if "http://" in text or "https://" in text:
        print("Refusing build with remote runtime asset URLs.", file=sys.stderr)
        return 4

    print(f"Workflow Studio static build ready: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
