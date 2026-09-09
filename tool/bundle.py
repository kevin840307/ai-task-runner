#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path

FORMAT = "PROJECT_BUNDLE_V1"
DEFAULT_EXCLUDES = [
    ".git", ".git/**",
    ".pytest_cache", ".pytest_cache/**",
    "__pycache__", "**/__pycache__", "**/__pycache__/**",
    "*.pyc", "**/*.pyc",
    ".ai-task-runner", "**/.ai-task-runner", "**/.ai-task-runner/**",
    "validator-reports", "**/validator-reports", "**/validator-reports/**",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def excluded(rel: str, patterns: list[str]) -> bool:
    p = Path(rel)
    runtime_dirs = {".git", ".pytest_cache", "__pycache__", ".ai-task-runner", "validator-reports"}
    if any(part in runtime_dirs for part in p.parts) or p.suffix == ".pyc":
        return True
    return any(p.match(x) for x in patterns)


def pack(root: Path, output: Path, excludes: list[str]) -> None:
    root = root.resolve()
    output = output.resolve()

    if not root.is_dir():
        raise SystemExit(f"Folder not found: {root}")

    count = 0
    total = 0

    with output.open("w", encoding="utf-8", newline="\n") as out:
        out.write(json.dumps({"format": FORMAT}, separators=(",", ":")) + "\n")

        for current, dirs, files in os.walk(root):
            current = Path(current)

            dirs[:] = [
                d for d in dirs
                if not excluded((current / d).relative_to(root).as_posix(), excludes)
            ]

            rel_dir = current.relative_to(root).as_posix()
            if rel_dir != "." and not dirs and not files:
                out.write(json.dumps(
                    {"type": "dir", "path": rel_dir},
                    separators=(",", ":")
                ) + "\n")

            for name in sorted(files):
                path = current / name
                rel = path.relative_to(root).as_posix()

                if excluded(rel, excludes):
                    continue

                data = path.read_bytes()
                record = {
                    "type": "file",
                    "path": rel,
                    "size": len(data),
                    "sha256": sha256(data),
                    "data": base64.b64encode(data).decode("ascii"),
                }
                out.write(json.dumps(record, separators=(",", ":")) + "\n")
                count += 1
                total += len(data)

    print(f"Packed {count} files, {total} bytes -> {output}")


def safe_target(root: Path, rel: str) -> Path:
    root = root.resolve()
    target = (root / rel).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"Unsafe path: {rel}")

    return target


def read_bundle(bundle: Path):
    with bundle.open("r", encoding="utf-8") as f:
        first = json.loads(f.readline())
        if first.get("format") != FORMAT:
            raise ValueError("Unsupported or invalid bundle format")

        for line_no, line in enumerate(f, 2):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid bundle at line {line_no}: {e}") from e


def unpack(bundle: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)

    count = 0
    total = 0

    for item in read_bundle(bundle):
        rel = item["path"]
        target = safe_target(output, rel)

        if item["type"] == "dir":
            target.mkdir(parents=True, exist_ok=True)
            continue

        if item["type"] != "file":
            raise ValueError(f"Unknown record type: {item['type']}")

        data = base64.b64decode(item["data"], validate=True)

        if len(data) != item["size"]:
            raise ValueError(f"Size mismatch: {rel}")
        if sha256(data) != item["sha256"]:
            raise ValueError(f"SHA256 mismatch: {rel}")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        count += 1
        total += len(data)

    print(f"Restored {count} files, {total} bytes -> {output.resolve()}")


def verify(bundle: Path) -> None:
    count = 0
    total = 0

    for item in read_bundle(bundle):
        if item["type"] == "dir":
            continue
        if item["type"] != "file":
            raise ValueError(f"Unknown record type: {item['type']}")

        data = base64.b64decode(item["data"], validate=True)
        rel = item["path"]

        if len(data) != item["size"]:
            raise ValueError(f"Size mismatch: {rel}")
        if sha256(data) != item["sha256"]:
            raise ValueError(f"SHA256 mismatch: {rel}")

        count += 1
        total += len(data)

    print(f"OK: {count} files, {total} bytes verified")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pack any folder into one copyable text file and restore it later."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pack")
    p.add_argument("folder", type=Path)
    p.add_argument("bundle", type=Path)
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude glob pattern. Repeat as needed, e.g. --exclude '.git/**'",
    )

    p = sub.add_parser("unpack")
    p.add_argument("bundle", type=Path)
    p.add_argument("output", type=Path)

    p = sub.add_parser("verify")
    p.add_argument("bundle", type=Path)

    args = parser.parse_args()

    try:
        if args.command == "pack":
            pack(args.folder, args.bundle, [*DEFAULT_EXCLUDES, *args.exclude])
        elif args.command == "unpack":
            unpack(args.bundle, args.output)
        else:
            verify(args.bundle)
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
