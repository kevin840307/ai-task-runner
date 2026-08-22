"""Child-process Git guard: repository publication remains a human action."""
from __future__ import annotations

import os
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

BLOCKED_GIT_SUBCOMMANDS = frozenset({"add", "commit", "push"})
_VALUE_OPTIONS = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace",
    "--super-prefix", "--config-env", "--exec-path",
})
_VALUE_PREFIXES = tuple(option + "=" for option in _VALUE_OPTIONS if option.startswith("--"))


def git_subcommand(args: list[str]) -> str:
    """Return the Git subcommand after common global options."""
    index = 0
    while index < len(args):
        value = args[index]
        if value in _VALUE_OPTIONS:
            index += 2
            continue
        if value.startswith(_VALUE_PREFIXES) or value.startswith("-"):
            index += 1
            continue
        return value.lower()
    return ""


def guarded_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Prepend a git wrapper that blocks staging/commit/push for AI child processes."""
    env = dict(os.environ if base is None else base)
    real_git = shutil.which("git", path=env.get("PATH"))
    if not real_git:
        return env
    guard = _guard_dir(Path(real_git).resolve())
    env["PATH"] = str(guard) + os.pathsep + env.get("PATH", "")
    return env


def guarded_command(
    command: Sequence[str],
    environment: Mapping[str, str],
) -> list[str]:
    """Resolve Windows Git calls to the guard wrapper prepended to PATH."""
    values = list(command)
    if os.name != "nt" or not values:
        return values
    if Path(values[0]).name.lower() not in {"git", "git.exe", "git.cmd"}:
        return values
    guard_root = environment.get("PATH", "").split(os.pathsep, 1)[0]
    wrapper = Path(guard_root) / "git.cmd"
    if wrapper.is_file():
        values[0] = str(wrapper)
    return values


def _guard_dir(real_git: Path) -> Path:
    key = str(abs(hash((str(real_git), sys.executable))))
    root = Path(tempfile.gettempdir()) / f"ai-task-runner-git-guard-{key}"
    root.mkdir(parents=True, exist_ok=True)
    helper = root / "guard.py"
    package_root = Path(__file__).resolve().parents[2]
    helper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(package_root)!r})\n"
        "from runner.safety.git_guard import _guard_main\n"
        "if __name__ == '__main__': raise SystemExit(_guard_main())\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = root / "git.cmd"
        wrapper.write_text(
            f'@"{sys.executable}" "{helper}" "{real_git}" %*\r\n',
            encoding="utf-8",
        )
    else:
        wrapper = root / "git"
        wrapper.write_text(
            "#!/bin/sh\nexec "
            + shlex.quote(sys.executable)
            + " "
            + shlex.quote(str(helper))
            + " "
            + shlex.quote(str(real_git))
            + ' "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return root


def _guard_main() -> int:
    import subprocess

    if len(sys.argv) < 2:
        return 2
    real_git, args = sys.argv[1], sys.argv[2:]
    subcommand = git_subcommand(args)
    if subcommand in BLOCKED_GIT_SUBCOMMANDS:
        print(
            f"AI Task Runner blocked 'git {subcommand}': human review is required.",
            file=sys.stderr,
        )
        return 126
    return subprocess.run([real_git, *args], check=False).returncode


__all__ = [
    "BLOCKED_GIT_SUBCOMMANDS",
    "_guard_main",
    "git_subcommand",
    "guarded_command",
    "guarded_environment",
]
