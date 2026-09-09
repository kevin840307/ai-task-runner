from __future__ import annotations

import base64
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 2
KIND = "workflow_folder"
_PROMPT_KEYS = {"prompt", "continuation_prompt"}
_EXCLUDED_DIR_NAMES = {"__pycache__", ".git", ".hg", ".svn", ".ai-task-runner", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_EXCLUDED_FILE_NAMES = {".DS_Store", "Thumbs.db"}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp"}
_EXCLUDED_ENDINGS = {".workflow-builder.tmp", ".workflow-builder.tmp.yaml", ".import-backup"}


def _iter_prompt_refs(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _PROMPT_KEYS and isinstance(child, str) and child.strip():
                yield child.strip()
            yield from _iter_prompt_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_prompt_refs(child)


def workflow_folder(workflow_path: Path, workflow_custom_root: Path) -> str:
    rel = workflow_path.resolve().relative_to(workflow_custom_root.resolve())
    folder = rel.parent.as_posix()
    if folder == ".":
        raise ValueError("Move this Workflow into a Custom folder before exporting the folder")
    if folder == "common" or folder.startswith("common/"):
        raise ValueError("The common folder cannot be exported as a Workflow folder")
    return folder


def classify_prompt_ref(ref: str, folder: str) -> tuple[str, str]:
    value = str(ref or "").strip().replace("\\", "/")
    if value.startswith("./"):
        value = value[2:]
    if (not value or value.startswith("/") or __import__("re").match(r"^[A-Za-z]:", value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError(f"Prompt is outside the portable folder scope: {ref}")
    if value.startswith("stages/") or value.startswith("system/"):
        return "system", value
    if value.startswith("custom/common/"):
        return "common", value
    own_prefix = f"custom/{folder}/"
    if value.startswith(own_prefix) and value != own_prefix:
        return "own", value
    raise ValueError(
        f"Prompt is outside the portable folder scope: {ref}. "
        f"Use custom/{folder}/..., custom/common/..., or system/stages prompts only."
    )



def _classify_export_prompt_ref(
    ref: str, folder: str, workflow_path: Path, prompt_global_root: Path, own_prompt_root: Path
) -> tuple[str, str]:
    """Classify one stored Prompt reference by its resolved ownership.

    Studio-authored Workflows normally use canonical ``custom/...`` references,
    while Workflow Builder publishes owned Prompts as paths relative to the
    Workflow file. Both are portable as long as the resolved target stays in
    the owned/common/system Prompt roots. Absolute references remain rejected.
    """
    value = str(ref or "").strip().replace("\\", "/")
    try:
        return classify_prompt_ref(value, folder)
    except ValueError:
        pass
    raw = Path(value)
    if not value or raw.is_absolute() or __import__("re").match(r"^[A-Za-z]:", value):
        raise ValueError(f"Prompt is outside the portable folder scope: {ref}")
    target = (workflow_path.parent / raw).resolve()
    roots = (
        ("own", own_prompt_root.resolve(), f"custom/{folder}"),
        ("common", (prompt_global_root / "custom" / "common").resolve(), "custom/common"),
        ("system", (prompt_global_root / "stages").resolve(), "stages"),
        ("system", (prompt_global_root / "system").resolve(), "system"),
    )
    for kind, root, canonical_prefix in roots:
        try:
            relative = target.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            break
        canonical = f"{canonical_prefix}/{relative.as_posix()}"
        return kind, canonical
    raise ValueError(
        f"Prompt is outside the portable folder scope: {ref}. "
        f"Use this Workflow's owned Prompt folder, custom/common, or system/stages prompts only."
    )

def _safe_rel(path: Path, root: Path) -> str:
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    if rel.startswith("../") or rel == "..":
        raise ValueError("Package path escapes its folder")
    return rel


def _excluded(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in _EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    if path.name in _EXCLUDED_FILE_NAMES:
        return True
    if path.suffix.lower() in _EXCLUDED_SUFFIXES:
        return True
    return any(path.name.endswith(ending) for ending in _EXCLUDED_ENDINGS)


def _snapshot_tree(root: Path) -> tuple[list[Path], list[str]]:
    """Return every owned regular file plus empty/non-empty directory paths.

    Portable Workflow folders intentionally preserve arbitrary support files
    (schemas, Python validators, JSON, Jinja templates, examples, assets, ...).
    Only explicit cache/runtime/temp artifacts are excluded. Symlinks are
    rejected so an exported folder cannot escape its ownership boundary.
    """
    if not root.exists():
        return [], []
    files: list[Path] = []
    directories: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlinks are not supported in portable Workflow folders: {path.name}")
        if _excluded(path, root):
            continue
        if path.is_dir():
            directories.append(_safe_rel(path, root))
        elif path.is_file():
            files.append(path)
    return files, directories


def _workflow_yaml_files(files: list[Path]) -> list[Path]:
    return [path for path in files if path.suffix.lower() in {".yaml", ".yml"}]


def export_folder_package(workflow_path: Path, repo_root: Path) -> dict:
    workflow_custom_root = repo_root / "runner" / "workflow" / "custom"
    prompt_global_root = repo_root / "runner" / "prompts"
    folder = workflow_folder(workflow_path, workflow_custom_root)
    workflow_root = (workflow_custom_root / folder).resolve()
    prompt_root = (prompt_global_root / "custom" / folder).resolve()

    workflow_files, workflow_dirs = _snapshot_tree(workflow_root)
    prompt_files, prompt_dirs = _snapshot_tree(prompt_root)
    workflow_yamls = _workflow_yaml_files(workflow_files)
    if not workflow_yamls:
        raise ValueError("Workflow folder contains no YAML Workflow files")

    dependencies: dict[str, str] = {}
    for wf in workflow_yamls:
        data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Workflow YAML root must be an object: {wf.name}")
        for ref in _iter_prompt_refs(data):
            kind, normalized = _classify_export_prompt_ref(
                ref, folder, wf, prompt_global_root, prompt_root
            )
            if kind == "own":
                target = (prompt_root / Path(normalized).relative_to(f"custom/{folder}")).resolve()
            else:
                target = (prompt_global_root / normalized).resolve()
            if not target.is_file():
                raise ValueError(f"Referenced Prompt does not exist: {normalized}")
            if kind != "own":
                dependencies[normalized] = kind

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "folder": folder,
        "workflow_files": [_safe_rel(p, workflow_root) for p in workflow_files],
        "workflow_dirs": workflow_dirs,
        "prompt_files": [_safe_rel(p, prompt_root) for p in prompt_files],
        "prompt_dirs": prompt_dirs,
        "dependencies": [{"scope": dependencies[p], "path": p} for p in sorted(dependencies)],
    }

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for rel in workflow_dirs:
            zf.writestr(f"workflow/{rel.rstrip('/')}/", b"")
        for path in workflow_files:
            zf.writestr(f"workflow/{_safe_rel(path, workflow_root)}", path.read_bytes())
        for rel in prompt_dirs:
            zf.writestr(f"prompts/{rel.rstrip('/')}/", b"")
        for path in prompt_files:
            zf.writestr(f"prompts/{_safe_rel(path, prompt_root)}", path.read_bytes())

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "folder": folder,
        "name": f"{folder.replace('/', '-')}.workflow-folder.zip",
        "mime": "application/zip",
        "encoding": "base64",
        "content": base64.b64encode(out.getvalue()).decode("ascii"),
        "workflow_path": f"runner/workflow/custom/{folder}",
        "prompt_path": f"runner/prompts/custom/{folder}",
        "workflow_file_count": len(workflow_files),
        "prompt_file_count": len(prompt_files),
    }


def _validate_rel(rel: str, name: str) -> str:
    raw = str(rel or "").replace("\\", "/").strip()
    if raw.startswith("/") or __import__("re").match(r"^[A-Za-z]:", raw):
        raise ValueError(f"Unsafe package path: {name}")
    raw = raw.strip("/")
    parts = Path(raw).parts
    if not raw or Path(raw).is_absolute() or any(part in {".", "..", ""} for part in parts):
        raise ValueError(f"Unsafe package path: {name}")
    return raw


def _read_package(content_b64: str) -> tuple[dict, dict[str, bytes], dict[str, bytes], list[str], list[str]]:
    try:
        raw = base64.b64decode(content_b64, validate=True)
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
    except Exception as exc:
        raise ValueError("Workflow folder package is not a valid ZIP") from exc

    names = zf.namelist()
    if "manifest.json" not in names:
        raise ValueError("Workflow folder package is missing manifest.json")
    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception as exc:
        raise ValueError("Workflow folder manifest is invalid") from exc
    version = int(manifest.get("schema_version", 0))
    if manifest.get("kind") != KIND or version not in {1, SCHEMA_VERSION}:
        raise ValueError("Unsupported Workflow folder package")

    def collect(prefix: str) -> tuple[dict[str, bytes], list[str]]:
        result: dict[str, bytes] = {}
        dirs: list[str] = []
        for name in names:
            if not name.startswith(prefix) or name == prefix:
                continue
            rel = _validate_rel(name[len(prefix):], name)
            if name.endswith("/"):
                dirs.append(rel)
                continue
            result[rel] = zf.read(name)
        return result, sorted(set(dirs))

    workflow_files, workflow_dirs = collect("workflow/")
    prompt_files, prompt_dirs = collect("prompts/")
    return manifest, workflow_files, prompt_files, workflow_dirs, prompt_dirs


def _manifest_folder(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or __import__("re").match(r"^[A-Za-z]:", raw):
        raise ValueError("Workflow folder name is invalid")
    raw = raw.rstrip("/")
    if (not raw or raw == "common" or raw.startswith("common/")
            or any(part in {"", ".", ".."} for part in raw.split("/"))):
        raise ValueError("Workflow folder name is invalid")
    return raw


def inspect_folder_package(content_b64: str) -> dict:
    manifest, workflow_files, prompt_files, _workflow_dirs, _prompt_dirs = _read_package(content_b64)
    folder = _manifest_folder(manifest.get("folder"))
    workflow_count = sum(1 for rel in workflow_files if Path(rel).suffix.lower() in {".yaml", ".yml"})
    return {
        "folder": folder,
        "workflow_count": workflow_count,
        "workflow_file_count": len(workflow_files),
        "prompt_file_count": len(prompt_files),
        # Backward-friendly label for the existing UI; now means all owned Prompt-folder files.
        "prompt_count": len(prompt_files),
        "total_file_count": len(workflow_files) + len(prompt_files),
        "workflow_path": f"runner/workflow/custom/{folder}",
        "prompt_path": f"runner/prompts/custom/{folder}",
    }


def import_folder_package(content_b64: str, repo_root: Path, validate_workflow, validate_prompt) -> tuple[str, list[Path]]:
    manifest, workflow_files, prompt_files, workflow_dirs, prompt_dirs = _read_package(content_b64)
    folder = _manifest_folder(manifest.get("folder"))
    workflow_yaml_rels = [rel for rel in workflow_files if Path(rel).suffix.lower() in {".yaml", ".yml"}]
    if not workflow_yaml_rels:
        raise ValueError("Workflow folder package contains no Workflow YAML")

    workflow_root = (repo_root / "runner" / "workflow" / "custom" / folder).resolve()
    prompt_root = (repo_root / "runner" / "prompts" / "custom" / folder).resolve()
    prompt_global = (repo_root / "runner" / "prompts").resolve()

    # Only Markdown Prompt templates need Prompt-template validation. Every other
    # owned support file is preserved byte-for-byte as part of the folder.
    for rel, raw in prompt_files.items():
        if Path(rel).suffix.lower() == ".md":
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Prompt Markdown must be UTF-8 text: {rel}") from exc
            validate_prompt(prompt_root / rel, text)

    # Shared/system Prompts are dependencies only and are never copied/deleted.
    for dep in manifest.get("dependencies") or []:
        ref = str((dep or {}).get("path") or "")
        kind, normalized = classify_prompt_ref(ref, folder)
        if kind == "own":
            raise ValueError("Own Prompt must be inside the package prompts folder")
        if not (prompt_global / normalized).is_file():
            raise ValueError(f"Required {kind} Prompt is missing: {normalized}")

    workflow_root.parent.mkdir(parents=True, exist_ok=True)
    prompt_root.parent.mkdir(parents=True, exist_ok=True)
    backup_wf = workflow_root.with_name(workflow_root.name + ".import-backup")
    backup_pr = prompt_root.with_name(prompt_root.name + ".import-backup")

    # Recover a previous interrupted import before starting a new transaction.
    # The backup is the last known-good folder; never silently discard it.
    for current, backup in ((workflow_root, backup_wf), (prompt_root, backup_pr)):
        if backup.exists():
            if current.exists():
                shutil.rmtree(current, ignore_errors=True)
            backup.rename(current)

    try:
        if workflow_root.exists():
            workflow_root.rename(backup_wf)
        if prompt_root.exists():
            prompt_root.rename(backup_pr)
        workflow_root.mkdir(parents=True, exist_ok=True)
        prompt_root.mkdir(parents=True, exist_ok=True)

        for rel in workflow_dirs:
            (workflow_root / rel).mkdir(parents=True, exist_ok=True)
        for rel in prompt_dirs:
            (prompt_root / rel).mkdir(parents=True, exist_ok=True)

        written_workflows: list[Path] = []
        for rel, raw in workflow_files.items():
            target = workflow_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            if target.suffix.lower() in {".yaml", ".yml"}:
                written_workflows.append(target)
        for rel, raw in prompt_files.items():
            target = prompt_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

        # Validate after staging so owned Prompt/support-file references resolve.
        for target in written_workflows:
            try:
                text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Workflow YAML must be UTF-8 text: {target.name}") from exc
            validate_workflow(target, text)
    except Exception:
        shutil.rmtree(workflow_root, ignore_errors=True)
        shutil.rmtree(prompt_root, ignore_errors=True)
        if backup_wf.exists():
            backup_wf.rename(workflow_root)
        if backup_pr.exists():
            backup_pr.rename(prompt_root)
        raise
    else:
        shutil.rmtree(backup_wf, ignore_errors=True)
        shutil.rmtree(backup_pr, ignore_errors=True)

    return folder, sorted([p for p in workflow_root.rglob("*") if p.is_file() and p.suffix.lower() in {".yaml", ".yml"}])
