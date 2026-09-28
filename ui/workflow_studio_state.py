"""Workflow Studio state operations extracted from the UI server.

This mixin owns editable Workflow/Prompt asset behavior. It deliberately depends
only on UI-local helpers and calls cross-domain runtime/project behavior through
`self`, keeping the public UIState surface unchanged.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import yaml
from jinja2 import Environment, meta

from project_registry import path_key

try:
    from .workflow_graph import build_workflow_graph
    from .workflow_storage import project_workflow_root
except ImportError:  # direct ui/main.py execution
    from workflow_graph import build_workflow_graph
    from workflow_storage import project_workflow_root


EDITABLE_SUFFIXES = {".yaml", ".yml", ".md"}


class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # noqa: ANN001
        return super().increase_indent(flow, False)


class WorkflowStudioMixin:
    # ------------------------------ workflow studio ------------------------------
    def studio_files(self, project: Path | None = None) -> dict:
        """List editable Workflow YAML and Prompt Markdown from the two asset roots."""
        roots: list[tuple[str, Path]] = [("global", self._global_asset_root())]
        if project is not None:
            roots.append(("project", project_workflow_root(project)))

        workflows: list[dict] = []
        prompts: list[dict] = []
        visibility = self._workflow_visibility()
        for scope, root in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
                workflows.append(self._studio_item(path, scope, "workflow", visibility))
            for path in sorted(root.glob("*.md")):
                prompts.append(self._studio_item(path, scope, "prompt"))

        order = {"global": 0, "project": 1}
        key = lambda item: (
            order.get(item["scope"], 9),
            item.get("display_name", item["name"]).lower(),
        )
        return {
            "workflows": sorted(workflows, key=key),
            "prompts": sorted(prompts, key=key),
            "guard": self.edit_guard(),
        }

    @staticmethod
    def _ast_dict_paths(node, prefix: str = "") -> list[str]:
        result: list[str] = []
        if not isinstance(node, ast.Dict):
            return result
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            path = f"{prefix}.{key_node.value}" if prefix else key_node.value
            result.append(path)
            result.extend(WorkflowStudioMixin._ast_dict_paths(value_node, path))
        return result

    @staticmethod
    def _ast_function_return(tree: ast.AST, name: str):
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                for child in ast.walk(node):
                    if isinstance(child, ast.Return):
                        return child.value
        return None

    def _stage_prompt_tag_paths(self) -> list[str]:
        """Read the stable Stage prompt context contract without importing Runner."""
        context_file = self.repo_root / "runner" / "prompts" / "context.py"
        try:
            tree = ast.parse(context_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise ValueError(f"Cannot read prompt context contract: {exc}") from exc
        paths = self._ast_dict_paths(self._ast_function_return(tree, "build_stage_prompt_context"))
        task_fields = self._ast_dict_paths(self._ast_function_return(tree, "_task_data"))
        paths.extend(f"task.{key}" for key in task_fields if "." not in key)
        return paths

    def _loader_prompt_contracts(self) -> dict[str, list[str]]:
        """Discover dedicated System Prompt variables from literal render_prompt calls.

        `system/rules.md` is not a Stage prompt. It is rendered by the prompt
        loader with its own values. Immutable output/retry protocols live in
        runner/prompts/protocols.py and are intentionally not Studio resources.
        Parse that contract statically so Workflow Studio does not import Runner Core
        and does not show false Prompt warnings when those files are inspected.
        """
        loader_file = self.repo_root / "runner" / "prompts" / "loader.py"
        prompt_root = self._global_asset_root()
        try:
            tree = ast.parse(loader_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return {}
        contracts: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "render_prompt":
                continue
            if len(node.args) < 2 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue
            paths = self._ast_dict_paths(node.args[1])
            if not paths:
                continue
            path = (prompt_root / node.args[0].value).resolve()
            contracts[os.path.normcase(str(path))] = paths
        return contracts

    def _prompt_tag_paths(self, prompt_path: Path | None = None) -> tuple[list[str], str]:
        if prompt_path is not None:
            dedicated = self._loader_prompt_contracts().get(os.path.normcase(str(prompt_path.resolve())))
            if dedicated:
                return dedicated, "loader"
        return self._stage_prompt_tag_paths(), "stage"

    def studio_prompt_tags(self, file_id: str = "", project: Path | None = None) -> dict:
        """Return valid insertable variables for the selected Prompt contract."""
        prompt_path: Path | None = None
        if str(file_id or "").strip():
            path, kind, _scope = self._resolve_studio_file(file_id, project)
            if kind != "prompt":
                raise ValueError("Prompt tags are available only for Prompt files")
            prompt_path = path
        paths, contract = self._prompt_tag_paths(prompt_path)
        seen: set[str] = set()
        tags = []
        descriptions = {
            "goal": "Current user goal / requirement.",
            "stage": "Current Stage key.",
            "project.root": "Current project root path.",
            "task.title": "Current task title when running per-task flow.",
            "task.description": "Current task description.",
            "task.acceptance_criteria": "Current task acceptance criteria.",
            "previous.output": "Previous Stage output, bounded by the runtime.",
            "previous.status": "Previous Stage result status.",
            "previous.data": "Structured data returned by the previous Stage.",
            "validation.feedback": "Latest validator feedback.",
            "workflow.validator_feedback": "Current workflow validator feedback.",
            "rules": "Runner AI rules for the project.",
            "always_instructions": "User-enforced always instructions.",
            "plugin_rules": "Plugin-provided Runner rules used by system/rules.md.",
        }
        for key in paths:
            if not key or key in seen:
                continue
            seen.add(key)
            tags.append({
                "key": key,
                "label": key.replace("_", " ").replace(".", " · ").title(),
                "description": descriptions.get(key, f"Runtime prompt context: {key}."),
            })
        source = str(prompt_path) if prompt_path is not None else str(self.repo_root / "runner" / "prompts" / "context.py")
        return {"tags": tags, "source": source, "contract": contract}

    def _check_prompt_content(self, content: str, prompt_path: Path | None = None) -> dict:
        """Validate Jinja syntax and variables against the actual Prompt contract."""
        env = Environment(autoescape=False)
        try:
            parsed = env.parse(content)
        except Exception as exc:
            line = int(getattr(exc, "lineno", 0) or 0)
            return {"ok": False, "summary": str(exc), "line": line, "unknown": [], "contract": "syntax"}
        paths, contract = self._prompt_tag_paths(prompt_path)
        variables = set(meta.find_undeclared_variables(parsed))
        allowed = {key.split(".", 1)[0] for key in paths}
        unknown = sorted(variables - allowed)
        return {
            "ok": not unknown,
            "summary": "Prompt valid" if not unknown else f"Unknown prompt variable(s): {', '.join(unknown)}",
            "unknown": unknown,
            "contract": contract,
        }

    def _validate_prompt_before_write(self, path: Path, content: str) -> dict:
        check = self._check_prompt_content(content, path)
        if not check["ok"]:
            raise ValueError("Prompt validation failed: " + check["summary"])
        return check

    def studio_prompt_check(self, file_id: str, content: str, project: Path | None = None) -> dict:
        path, kind, _scope = self._resolve_studio_file(file_id, project)
        if kind != "prompt":
            raise ValueError("Prompt check is available only for Prompt files")
        return self._check_prompt_content(content, path)

    def studio_workflow_create(
        self,
        name: str,
        destination: str,
        project: Path | None = None,
    ) -> dict:
        """Create one editable Workflow in Global or Project assets."""
        with self._edit_lock:
            self._require_editable()
            raw = self._normalize_studio_asset_name("workflow", name)
            scope = self._normalize_asset_scope(destination)
            root = self._asset_root(scope, project)
            root.mkdir(parents=True, exist_ok=True)
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"Workflow already exists: {target.name}")
            content = (
                "stages:\n"
                "  start:\n"
                "    type: base\n"
                "    prompt: execution.md\n\n"
                "flow:\n"
                "  - start\n"
            )
            self._validate_workflow_before_write(target, content)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            item = self._studio_item(target, scope, "workflow")
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_read(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, scope = self._resolve_studio_file(file_id, project)
        content = path.read_text(encoding="utf-8")
        stat = path.stat()
        return {
            **self._studio_item(path, scope, kind),
            "content": content,
            "hash": self._hash_text(content),
            "mtime": stat.st_mtime,
            "guard": self.edit_guard(),
        }

    def studio_save(self, file_id: str, content: str, expected_hash: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            guard = self.edit_guard()
            if not guard["editable"]:
                names = ", ".join(p["name"] for p in guard["active_projects"])
                raise ValueError(f"Cannot edit workflow/prompt while runtime is active: {names}")
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if path.suffix.lower() not in EDITABLE_SUFFIXES:
                raise ValueError("Unsupported file type")
            current = path.read_text(encoding="utf-8")
            current_hash = self._hash_text(current)
            if expected_hash and expected_hash != current_hash:
                raise ValueError("File changed on disk. Reload before saving to avoid overwriting another editor.")
            if kind == "workflow":
                self._validate_workflow_before_write(path, content)
            elif kind == "prompt":
                self._validate_prompt_before_write(path, content)
            self._atomic_write(path, content)
            return self.studio_read(file_id, project)

    def studio_visual(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, scope = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            raise ValueError("Visual designer is available only for workflow YAML")
        content = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Workflow YAML root must be a mapping")
        stages_raw = data.get("stages") or {}
        if not isinstance(stages_raw, dict):
            stages_raw = {}
        stages = []
        for name, cfg in stages_raw.items():
            config = cfg if isinstance(cfg, dict) else {}
            stages.append({
                "name": str(name),
                **config,
                "type": str(config.get("type") or "base"),
                "status": str(config.get("status") or ""),
                "prompt": str(config.get("prompt") or ""),
            })
        flow_raw = data.get("flow") or []
        flow = [
            item for item in flow_raw
            if isinstance(item, str) and item.strip()
        ] if isinstance(flow_raw, list) else []
        return {
            "id": file_id,
            "name": path.name,
            "scope": scope,
            "hash": self._hash_text(content),
            "stages": stages,
            "flow": flow,
            "guard": self.edit_guard(),
        }

    def studio_visual_save(self, file_id: str, flow: list, expected_hash: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            guard = self.edit_guard()
            if not guard["editable"]:
                names = ", ".join(p["name"] for p in guard["active_projects"])
                raise ValueError(f"Cannot edit workflow/prompt while runtime is active: {names}")
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if kind != "workflow":
                raise ValueError("Visual designer is available only for workflow YAML")
            content = path.read_text(encoding="utf-8")
            current_hash = self._hash_text(content)
            if expected_hash and expected_hash != current_hash:
                raise ValueError("File changed on disk. Reload before saving to avoid overwriting another editor.")
            try:
                data = yaml.safe_load(content) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("Workflow YAML root must be a mapping")
            normalized = [
                item.strip()
                for item in flow if isinstance(flow, list)
                if isinstance(item, str) and item.strip()
            ]
            # Reuse the canonical Flow block writer instead of emitting an
            # indentless sequence here.  The Visual editor must never turn a
            # valid Workflow into malformed YAML merely by reordering Stages.
            updated = self._replace_flow_block(content, normalized)
            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            return self.studio_read(file_id, project)

    def studio_stage_save(
        self,
        file_id: str,
        stage_name: str,
        fields: dict,
        expected_hash: str,
        project: Path | None = None,
        *,
        validate_only: bool = False,
    ) -> dict:
        """Patch or validate one n8n-style Stage node."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope_name = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope_name)
            if kind != "workflow":
                raise ValueError("Stage editor is available only for workflow YAML")

            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            data = self._load_workflow_yaml(content)
            stages = data.get("stages") if isinstance(data, dict) else None
            if not isinstance(stages, dict) or stage_name not in stages:
                raise ValueError(f"Stage not found: {stage_name}")

            allowed = {
                "type", "status", "run_state", "actor", "mode", "prompt",
                "continuation_prompt", "instructions", "detail", "produces",
                "session_key", "parser", "cwd", "result_kind", "validator", "command",
                "allow_project_read", "track_changes", "tolerate_restored_changes",
                "fresh_session_each_run", "fresh_session_on_start",
                "structured_retries", "structured_fresh_retries",
                "runs", "required_passes", "min_tasks", "timeout",
                "clean_work", "label", "scope", "routes",
            }
            if not isinstance(fields, dict):
                raise ValueError("Stage fields must be an object")
            clean = {}
            for key, value in fields.items():
                if key not in allowed:
                    raise ValueError(f"Unsupported Stage field: {key}")
                clean[key] = value

            self._validate_stage_editor_fields(clean)
            self._validate_node_editor_fields(clean, data)
            updated = self._patch_stage_fields(content, stage_name, clean)

            parsed = self._load_workflow_yaml(updated)
            final_stage = (parsed.get("stages") or {}).get(stage_name, {})
            if (
                isinstance(final_stage, dict)
                and final_stage.get("type") == "command"
                and not final_stage.get("command")
            ):
                raise ValueError("Command Stage requires a command")

            validation = self._validate_workflow_before_write(path, updated)
            if validate_only:
                return {
                    "ok": True,
                    "summary": "Validation passed",
                    "output": validation.get("output", "")[-20000:],
                }
            self._atomic_write(path, updated)
            return {
                "file": self.studio_read(file_id, project),
                "visual": self.studio_visual(file_id, project),
            }

    def studio_stage_add(
        self,
        file_id: str,
        stage_name: str,
        stage_type: str,
        expected_hash: str,
        project: Path | None = None,
        *,
        status: str = "",
        prompt: str = "",
        command: str = "",
        add_to_flow: bool = True,
    ) -> dict:
        """Insert one Stage with minimal YAML churn, then optionally append it to flow."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope_name = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope_name)
            if kind != "workflow":
                raise ValueError("Stages can be added only to workflow YAML")
            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            name = str(stage_name or "").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
                raise ValueError("Stage key must start with a letter/underscore and contain only letters, numbers, _ or -")
            stage_type = str(stage_type or "base").strip()
            if stage_type not in self._supported_stage_types():
                raise ValueError("Unsupported Stage type")
            data = self._load_workflow_yaml(content)
            stages = data.get("stages") if isinstance(data, dict) else None
            if isinstance(stages, dict) and name in stages:
                raise ValueError(f"Stage already exists: {name}")
            if stage_type == "command" and not str(command or "").strip():
                raise ValueError("Command Stage requires a command")
            if stage_type == "base" and not str(prompt or "").strip():
                raise ValueError("Base Stage requires a Prompt")
            if str(prompt or "").strip() and self._resolve_prompt_reference(path, str(prompt).strip()) is None:
                raise ValueError(f"Prompt not found: {str(prompt).strip()}")

            config: dict = {"type": stage_type}
            if status.strip(): config["status"] = status.strip()
            if prompt.strip(): config["prompt"] = prompt.strip()
            if stage_type == "command": config["command"] = command.strip()
            if stage_type == "ai_validator": config.setdefault("validator", "ai")
            updated = self._insert_stage_block(content, name, config)
            if add_to_flow:
                parsed = self._load_workflow_yaml(updated)
                flow = parsed.get("flow") if isinstance(parsed, dict) else []
                flow = list(flow) if isinstance(flow, list) else []
                flow.append(name)
                updated = self._replace_flow_block(updated, flow)
            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            return {"file": self.studio_read(file_id, project), "visual": self.studio_visual(file_id, project)}

    def studio_check(self, file_id: str, content: str, project: Path | None = None) -> dict:
        _path, kind, _scope = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            return {"ok": True, "summary": "Markdown"}
        try:
            value = yaml.safe_load(content)
            if value is not None and not isinstance(value, dict):
                return {"ok": False, "summary": "YAML root must be a mapping", "line": 1, "column": 1}
            return {"ok": True, "summary": "YAML valid"}
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = int(getattr(mark, "line", 0)) + 1 if mark is not None else 0
            column = int(getattr(mark, "column", 0)) + 1 if mark is not None else 0
            message = getattr(exc, "problem", None) or str(exc).splitlines()[0]
            return {"ok": False, "summary": str(message), "line": line, "column": column}

    def _validate_stage_editor_fields(self, fields: dict) -> None:
        stage_type = fields.get("type")
        if stage_type is not None:
            if stage_type not in self._supported_stage_types():
                raise ValueError("Unsupported Stage type")
        mode = fields.get("mode")
        if mode not in (None, "", "readonly", "write"):
            raise ValueError("Stage mode must be readonly or write")
        parser = fields.get("parser")
        if parser not in (None, "", "review", "validation"):
            raise ValueError("Stage parser must be review or validation")
        produces = fields.get("produces")
        if produces not in (None, "", "tasks"):
            raise ValueError("Stage produces must be tasks when specified")
        for key in ("structured_retries", "structured_fresh_retries", "runs", "required_passes", "min_tasks"):
            value = fields.get(key)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Stage {key} must be an integer")
            minimum = 1 if key in {"runs", "min_tasks"} else 0
            if value < minimum:
                raise ValueError(f"Stage {key} must be >= {minimum}")
        timeout = fields.get("timeout")
        if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout < 0):
            raise ValueError("Stage timeout must be a non-negative number")

    @staticmethod
    def _validate_node_editor_fields(updates: dict, workflow: dict) -> None:
        scope = updates.get("scope")
        if scope not in (None, "", "task"):
            raise ValueError("Stage scope must be task when specified")
        label = updates.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise ValueError("Stage label must be a non-empty string")

        routes = updates.get("routes")
        if routes is None:
            return
        if not isinstance(routes, dict) or not routes:
            raise ValueError("Stage routes must be a non-empty object")
        unknown = sorted(str(key) for key in routes if key not in {"pass", "fail", "error"})
        if unknown:
            raise ValueError(
                "Stage routes supports only pass/fail/error; unknown: "
                + ", ".join(unknown)
            )

        stages = workflow.get("stages") if isinstance(workflow, dict) else {}
        targets = set(stages) if isinstance(stages, dict) else set()
        targets.update({"next", "done", "stop"})
        for status, target in routes.items():
            if not isinstance(target, str) or not target.strip():
                raise ValueError(f"Stage routes.{status} must be a non-empty target")
            if target not in targets:
                raise ValueError(
                    f"Stage routes.{status} references unknown Stage: {target}"
                )

    def _require_editable(self) -> None:
        guard = self.edit_guard()
        if not guard["editable"]:
            names = ", ".join(p["name"] for p in guard["active_projects"])
            raise ValueError(f"Cannot edit workflow/prompt while runtime is active: {names}")

    def _require_hash(self, content: str, expected_hash: str) -> None:
        if expected_hash and expected_hash != self._hash_text(content):
            raise ValueError("File changed on disk. Reload before saving to avoid overwriting another editor.")

    @staticmethod
    def _load_workflow_yaml(content: str) -> dict:
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Workflow YAML root must be a mapping")
        return data

    @staticmethod
    def _stage_bounds(lines: list[str], stage_name: str) -> tuple[int, int]:
        stages_start = next((i for i, line in enumerate(lines) if re.match(r"^stages:\s*(?:#.*)?$", line.rstrip("\r\n"))), None)
        if stages_start is None:
            raise ValueError("Workflow has no top-level stages mapping")
        stage_pattern = re.compile(rf"^  {re.escape(stage_name)}:(?:\s*&[^\s#]+)?\s*(?:#.*)?$")
        start = next((i for i in range(stages_start + 1, len(lines)) if stage_pattern.match(lines[i].rstrip("\r\n"))), None)
        if start is None:
            raise ValueError(f"Stage uses unsupported YAML key syntax: {stage_name}")
        end = len(lines)
        for i in range(start + 1, len(lines)):
            text = lines[i]
            if re.match(r"^  [^\s#][^:]*:", text) or (text.strip() and not text[:1].isspace() and not text.lstrip().startswith("#")):
                end = i
                break
        return start, end

    @classmethod
    def _patch_stage_fields(cls, content: str, stage_name: str, fields: dict) -> str:
        lines = content.splitlines(keepends=True)
        newline = "\r\n" if "\r\n" in content else "\n"
        for key, value in fields.items():
            start, end = cls._stage_bounds(lines, stage_name)
            field_pattern = re.compile(rf"^    {re.escape(key)}:\s*")
            field_start = next((i for i in range(start + 1, end) if field_pattern.match(lines[i])), None)
            field_end = field_start
            if field_start is not None:
                field_end = end
                for i in range(field_start + 1, end):
                    candidate = lines[i]
                    leading = len(candidate) - len(candidate.lstrip(" "))
                    if (
                        re.match(r"^    [A-Za-z_][A-Za-z0-9_-]*:\s*", candidate)
                        or (candidate.lstrip().startswith("#") and leading <= 4)
                        or not candidate.strip()
                        or (candidate.strip() and not candidate[:1].isspace())
                    ):
                        field_end = i
                        break
            replacement: list[str] = []
            if value is not None:
                dumped = yaml.dump({key: value}, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
                replacement = [f"    {line}{newline}" for line in dumped.splitlines()]
            if field_start is not None:
                lines[field_start:field_end] = replacement
            elif replacement:
                _start, end = cls._stage_bounds(lines, stage_name)
                lines[end:end] = replacement
        return "".join(lines)

    @classmethod
    def _insert_stage_block(cls, content: str, stage_name: str, config: dict) -> str:
        newline = "\r\n" if "\r\n" in content else "\n"
        dumped = yaml.dump(config, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
        block = f"  {stage_name}:{newline}" + "".join(f"    {line}{newline}" for line in dumped.splitlines())
        lines = content.splitlines(keepends=True)
        stages_start = next((i for i, line in enumerate(lines) if re.match(r"^stages:\s*(?:#.*)?$", line.rstrip("\r\n"))), None)
        if stages_start is None:
            prefix = f"stages:{newline}{block}{newline}"
            return prefix + content
        end = len(lines)
        for i in range(stages_start + 1, len(lines)):
            line = lines[i]
            if line.strip() and not line[:1].isspace() and not line.lstrip().startswith("#"):
                end = i
                break
        prefix_blank = [] if end == 0 or (end > 0 and not lines[end - 1].strip()) else [newline]
        lines[end:end] = prefix_blank + [block]
        return "".join(lines)

    @staticmethod
    def _replace_flow_block(content: str, flow: list) -> str:
        normalized = []
        for item in flow if isinstance(flow, list) else []:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
            elif isinstance(item, dict) and str(item.get("stage", "")).strip():
                clean = dict(item)
                clean["stage"] = str(clean["stage"]).strip()
                normalized.append(clean if len(clean) > 1 else clean["stage"])
        flow_text = yaml.dump({"flow": normalized}, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip() + "\n"
        lines = content.splitlines(keepends=True)
        start = next((i for i, line in enumerate(lines) if line.startswith("flow:") and not line[:1].isspace()), None)
        if start is None:
            separator = "" if not content or content.endswith("\n") else "\n"
            return content + separator + flow_text
        end = len(lines)
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and not line[:1].isspace() and not line.lstrip().startswith("#"):
                end = i
                break
        return "".join(lines[:start]) + flow_text + "".join(lines[end:])

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    def _validate_workflow_before_write(self, path: Path, content: str) -> dict:
        """Run prompt-reference checks and the real dry-run before any Workflow write."""
        self._load_workflow_yaml(content)
        self._validate_workflow_prompt_refs(path, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        suffix = path.suffix if path.suffix.lower() in {".yaml", ".yml"} else ".yaml"
        temporary = path.with_name(f".{path.stem}.ui-validate-{uuid.uuid4().hex[:8]}{suffix}")
        temporary.write_text(content, encoding="utf-8")
        try:
            command = [sys.executable, str(self.repo_root / "tool" / "workflow_dryrun.py"), str(temporary), "--matrix", "--json", "--max-steps", "500"]
            try:
                result = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=45)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Workflow validation timed out after 45 seconds") from exc
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode != 0:
                raise ValueError("Workflow validation failed: " + output[-12000:])
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("Workflow validation returned invalid JSON") from exc
            if not payload.get("closed"):
                raise ValueError("Workflow validation matrix did not reach closure")
            return {"ok": True, "output": output, "payload": payload}
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _require_studio_writable(self, scope: str) -> None:
        if scope in SYSTEM_SCOPES:
            raise ValueError("System workflow/prompt is read only. Create or import a Custom copy to edit it.")

    def _workflow_requirements(self, path: Path | None) -> dict:
        result = {"requires_python_validator": False, "has_ai_validator": False}
        if path is None or not path.is_file():
            return result
        try:
            stat = path.stat()
            key = os.path.normcase(str(path.resolve()))
            cached = self._workflow_requirement_cache.get(key)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                return dict(cached[2])
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return result
        stages = data.get("stages") if isinstance(data, dict) else {}
        flow = data.get("flow") if isinstance(data, dict) else []
        if not isinstance(stages, dict) or not isinstance(flow, list):
            return result
        seen: set[tuple[str, str]] = set()

        def visit(item) -> None:
            if isinstance(item, str):
                name, overrides = item, {}
            elif isinstance(item, dict):
                name, overrides = str(item.get("stage", "")), {k: v for k, v in item.items() if k != "stage"}
            else:
                return
            cfg = dict(stages.get(name) or {}) if isinstance(stages.get(name), dict) else {}
            cfg.update(overrides)
            signature = (name, json.dumps(cfg, ensure_ascii=False, sort_keys=True, default=str))
            if signature in seen:
                return
            seen.add(signature)
            stage_type = str(cfg.get("type") or "base")
            if stage_type == "ai_validator":
                result["has_ai_validator"] = True
            command = cfg.get("command")
            command_text = " ".join(command) if isinstance(command, list) else str(command or "")
            if stage_type == "command" and str(cfg.get("result_kind") or "") == "validation" and "{validator}" in command_text:
                result["requires_python_validator"] = True

        for row in flow:
            visit(row)
        self._workflow_requirement_cache[key] = (stat.st_mtime_ns, stat.st_size, dict(result))
        return result

    def _resolve_prompt_reference(self, workflow_path: Path, reference: str) -> Path | None:
        value = str(reference or "").strip()
        if not value:
            return None
        raw = Path(value).expanduser()
        candidates = [raw] if raw.is_absolute() else [
            workflow_path.parent / raw,
            self.repo_root / "runner" / "prompts" / raw,
        ]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_file() and resolved.suffix.lower() == ".md":
                return resolved
        return None

    def _workflow_prompt_refs(self, content: str) -> list[tuple[str, str]]:
        data = self._load_workflow_yaml(content)
        stages = data.get("stages") or {}
        flow = data.get("flow") or []
        refs: list[tuple[str, str]] = []
        if not isinstance(stages, dict):
            return refs
        for name, config in stages.items():
            if not isinstance(config, dict):
                continue
            stage_type = str(config.get("type") or "base")
            if stage_type == "base" and not str(config.get("prompt") or "").strip():
                refs.append((str(name), "<required>"))
            for key in ("prompt", "continuation_prompt"):
                value = config.get(key)
                if isinstance(value, str) and value.strip():
                    refs.append((str(name), value.strip()))
        if isinstance(flow, list):
            for index, item in enumerate(flow):
                if isinstance(item, dict):
                    name = str(item.get("stage") or f"flow[{index}]")
                    for key in ("prompt", "continuation_prompt"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            refs.append((name, value.strip()))
        return refs

    def _validate_workflow_prompt_refs(self, workflow_path: Path, content: str) -> None:
        missing: list[str] = []
        for stage, reference in self._workflow_prompt_refs(content):
            if reference == "<required>":
                missing.append(f"{stage}: Prompt is required")
            elif self._resolve_prompt_reference(workflow_path, reference) is None:
                missing.append(f"{stage}: {reference}")
        if missing:
            raise ValueError("Workflow references missing Prompt(s): " + "; ".join(missing[:12]))

    def _known_workflow_paths(self, project: Path | None = None) -> list[Path]:
        roots = [self._global_asset_root()]
        known_projects = [
            Path(row["path"]).absolute()
            for row in self.projects()
            if row.get("exists")
        ]
        if project is not None:
            project_path = Path(project).absolute()
            if all(path_key(project_path) != path_key(item) for item in known_projects):
                known_projects.append(project_path)
        roots.extend(project_workflow_root(item) for item in known_projects)

        result: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for pattern in ("*.yaml", "*.yml"):
                for path in root.glob(pattern):
                    resolved = path.resolve()
                    key = path_key(resolved)
                    if key not in seen:
                        seen.add(key)
                        result.append(resolved)
        return result

    def _prompt_usages(self, prompt_path: Path, project: Path | None = None) -> list[str]:
        target = prompt_path.resolve()
        usages: list[str] = []
        for workflow in self._known_workflow_paths(project):
            try:
                content = workflow.read_text(encoding="utf-8")
            except OSError:
                continue
            for stage, reference in self._workflow_prompt_refs(content):
                resolved = self._resolve_prompt_reference(workflow, reference)
                if resolved is not None and os.path.normcase(str(resolved)) == os.path.normcase(str(target)):
                    usages.append(f"{workflow.name} · {stage}")
        return sorted(set(usages))

    def studio_prompt_create(
        self,
        name: str,
        destination: str,
        project: Path | None = None,
    ) -> dict:
        with self._edit_lock:
            self._require_editable()
            raw = self._normalize_studio_asset_name("prompt", name)
            scope = self._normalize_asset_scope(destination)
            root = self._asset_root(scope, project)
            root.mkdir(parents=True, exist_ok=True)
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"Prompt already exists: {target.name}")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write("# Prompt\n\n{{ goal }}\n")
            item = self._studio_item(target, scope, "prompt")
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_delete(self, file_id: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            usages = self._prompt_usages(path, project) if kind == "prompt" else []
            if usages:
                raise ValueError("Prompt is still used by Workflow Stage(s): " + "; ".join(usages[:12]))
            try:
                path.unlink()
            except OSError as exc:
                raise ValueError(f"Cannot delete {kind}: {exc}") from exc
            return {"ok": True, "kind": kind, "name": path.name}

    @staticmethod
    def _normalize_studio_asset_name(kind: str, name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            raise ValueError(f"{kind.title()} name is required")
        if "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise ValueError(f"{kind.title()} name must be a file name, not a path")
        if kind == "workflow":
            if not raw.lower().endswith((".yaml", ".yml")):
                raw += ".workflow.yaml" if "workflow" not in raw.lower() else ".yaml"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", raw, re.IGNORECASE):
                raise ValueError("Workflow file name contains unsupported characters")
        elif kind == "prompt":
            if not raw.lower().endswith(".md"):
                raw += ".md"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.md", raw, re.IGNORECASE):
                raise ValueError("Prompt file name contains unsupported characters")
        else:
            raise ValueError("Unsupported Studio asset kind")
        return raw

    def _studio_scope_root(
        self, kind: str, scope: str, project: Path | None
    ) -> Path:
        del kind
        root = self._asset_root(scope, project)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def studio_rename(
        self,
        file_id: str,
        name: str,
        project: Path | None = None,
    ) -> dict:
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            if kind == "prompt":
                usages = self._prompt_usages(path, project)
                if usages:
                    raise ValueError(
                        "Prompt is still referenced; update Workflow references before rename: "
                        + "; ".join(usages[:12])
                    )
            raw = self._normalize_studio_asset_name(kind, name)
            root = self._asset_root(scope, project)
            target = (root / raw).resolve()
            if target == path:
                item = self._studio_item(path, scope, kind)
                return {"item": item, "file": self.studio_read(item["id"], project)}
            if target.exists():
                raise ValueError(f"{kind.title()} already exists: {target.name}")
            content = path.read_text(encoding="utf-8")
            if kind == "workflow":
                self._validate_workflow_before_write(target, content)
            else:
                self._validate_prompt_before_write(target, content)
            path.rename(target)
            item = self._studio_item(target, scope, kind)
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_duplicate(
        self,
        file_id: str,
        name: str,
        project: Path | None = None,
    ) -> dict:
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            raw = self._normalize_studio_asset_name(kind, name)
            root = self._asset_root(scope, project)
            root.mkdir(parents=True, exist_ok=True)
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"{kind.title()} already exists: {target.name}")
            content = path.read_text(encoding="utf-8")
            if kind == "workflow":
                self._validate_workflow_before_write(target, content)
            else:
                self._validate_prompt_before_write(target, content)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
            item = self._studio_item(target, scope, kind)
            return {"item": item, "file": self.studio_read(item["id"], project)}

    @staticmethod
    def _stage_reference_paths    @staticmethod
    def _stage_reference_paths(value, stage_name: str, path: str = "workflow") -> list[str]:
        refs: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                current = f"{path}.{key}"
                if key == "stage" and isinstance(child, str) and child == stage_name:
                    refs.append(current)
                    continue
                if key == "routes" and isinstance(child, dict):
                    for status, target in child.items():
                        if isinstance(target, str) and target == stage_name:
                            refs.append(f"{current}.{status}")
                    continue
                refs.extend(
                    WorkflowStudioMixin._stage_reference_paths(
                        child, stage_name, current
                    )
                    if isinstance(child, (dict, list))
                    else []
                )
        elif isinstance(value, list):
            for index, child in enumerate(value):
                current = f"{path}[{index}]"
                if isinstance(child, str) and child == stage_name:
                    refs.append(current)
                elif isinstance(child, (dict, list)):
                    refs.extend(
                        WorkflowStudioMixin._stage_reference_paths(
                            child, stage_name, current
                        )
                    )
        return refs

    @staticmethod
    def _remove_stage_definition_block(content: str, stage_name: str) -> str:
        try:
            root = yaml.compose(content)
        except yaml.YAMLError as exc:
            raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
        if not isinstance(root, yaml.nodes.MappingNode):
            raise ValueError("Workflow YAML root must be a mapping")
        stage_mapping = None
        for key_node, value_node in root.value:
            if isinstance(key_node, yaml.nodes.ScalarNode) and key_node.value == "stages":
                stage_mapping = value_node
                break
        if not isinstance(stage_mapping, yaml.nodes.MappingNode):
            raise ValueError("Workflow stages mapping is missing")
        start = end = None
        for key_node, value_node in stage_mapping.value:
            if isinstance(key_node, yaml.nodes.ScalarNode) and str(key_node.value) == stage_name:
                start = key_node.start_mark.line
                end = max(key_node.end_mark.line, value_node.end_mark.line)
                break
        if start is None or end is None:
            raise ValueError(f"Stage not found: {stage_name}")
        lines = content.splitlines(keepends=True)
        del lines[start:end]
        return "".join(lines)

    def studio_stage_delete(
        self,
        file_id: str,
        stage_name: str,
        expected_hash: str,
        project: Path | None = None,
    ) -> dict:
        """Delete one Stage node after proving no result edge still targets it."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if kind != "workflow":
                raise ValueError("Stage definitions exist only in Workflow YAML")

            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            data = self._load_workflow_yaml(content)
            stages = data.get("stages") if isinstance(data, dict) else None
            flow = data.get("flow") if isinstance(data, dict) else None
            if not isinstance(stages, dict) or stage_name not in stages:
                raise ValueError(f"Stage not found: {stage_name}")
            if not isinstance(flow, list) or stage_name not in flow:
                raise ValueError("Stage is not present in Workflow flow")

            next_flow = [name for name in flow if name != stage_name]
            next_stages = dict(stages)
            next_stages.pop(stage_name, None)
            next_data = {**data, "stages": next_stages, "flow": next_flow}
            refs = self._stage_reference_paths(next_data, stage_name)
            if refs:
                raise ValueError(
                    "Stage definition is still referenced by: " + ", ".join(refs[:8])
                )

            without_stage = self._remove_stage_definition_block(content, stage_name)
            updated = self._replace_flow_block(without_stage, next_flow)
            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            return {
                "file": self.studio_read(file_id, project),
                "visual": self.studio_visual(file_id, project),
            }

    def studio_export(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, scope = self._resolve_studio_file(file_id, project)
        return {
            "schema_version": 1,
            "kind": kind,
            "name": path.name,
            "scope": scope,
            "content": path.read_text(encoding="utf-8"),
        }

    def studio_graph(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, _scope = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            raise ValueError("Flow Map is available only for Workflow YAML")
        data = self._load_workflow_yaml(path.read_text(encoding="utf-8"))
        return build_workflow_graph(data)

    def studio_import(
        self,
        kind: str,
        name: str,
        content: str,
        destination: str,
        project: Path | None = None,
    ) -> dict:
        with self._edit_lock:
            self._require_editable()
            kind = str(kind or "").strip().lower()
            if kind not in {"workflow", "prompt"}:
                raise ValueError("Import kind must be workflow or prompt")
            scope = self._normalize_asset_scope(destination)
            root = self._asset_root(scope, project)
            root.mkdir(parents=True, exist_ok=True)
            raw = self._normalize_studio_asset_name(kind, name or f"imported-{kind}")
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"Asset already exists: {target.name}")
            text = str(content or "")
            if not text.strip():
                raise ValueError("Imported content is empty")
            if kind == "workflow":
                self._validate_workflow_before_write(target, text)
            else:
                self._validate_prompt_before_write(target, text)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            item = self._studio_item(target, scope, kind)
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_validate(
        self,
        file_id: str,
        project: Path | None = None,
        *,
        content: str | None = None,
        flow: object | None = None,
    ) -> dict:
        """Validate the current Workflow draft without writing it.

        YAML mode can pass ``content`` while Visual mode can pass the current ``flow``.
        The real Workflow file remains untouched; the existing dry-run gate receives only
        a temporary validation copy.
        """
        path, kind, _ = self._resolve_studio_file(file_id, project)
        draft = path.read_text(encoding="utf-8") if content is None else str(content)
        if kind == "prompt":
            check = self._check_prompt_content(draft, path)
            if not check["ok"]:
                return {**check, "summary": "Prompt validation failed", "output": check["summary"]}
            return {**check, "summary": "Prompt validation passed", "output": ""}
        if kind != "workflow":
            raise ValueError("Only Workflow or Prompt files can be validated")
        if flow is not None:
            if not isinstance(flow, list):
                return {"ok": False, "summary": "Validation failed", "output": "Workflow flow must be a list"}
            draft = self._replace_flow_block(draft, flow)
        try:
            result = self._validate_workflow_before_write(path, draft)
        except ValueError as exc:
            return {"ok": False, "summary": "Validation failed", "output": str(exc)}
        return {"ok": True, "summary": "Validation passed", "output": result.get("output", "")[-20000:]}







    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def _normalize_workflow_folder(cls, folder: str) -> str:
        raw = str(folder or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("Workflow folder is required")
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            raise ValueError("Workflow folder must be a relative path")
        raw = raw.rstrip("/")
        parts = Path(raw).parts
        if ".." in parts or "." in parts or any(not part for part in parts):
            raise ValueError("Workflow folder contains an invalid path segment")
        if raw == "common" or raw.startswith("common/"):
            raise ValueError("The common folder is reserved and cannot own a Workflow")
        if any(cls._is_technical_folder_part(part) for part in parts):
            raise ValueError("Workflow folder contains a reserved technical directory")
        if not all(re.fullmatch(r"[A-Za-z0-9_. -]+", part) for part in parts):
            raise ValueError("Workflow folder contains unsupported characters")
        return "/".join(parts)

    def _workflow_output_paths(self, project: Path | None, folder: str, filename: str, destination: str) -> tuple[str, str, str, Path, Path]:
        folder = self._normalize_workflow_folder(folder)
        raw = str(filename or "").strip()
        if not raw:
            raise ValueError("Workflow filename is required")
        if "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise ValueError("Workflow filename must be a file name, not a path")
        if not raw.lower().endswith((".yaml", ".yml")):
            raw += ".workflow.yaml" if "workflow" not in raw.lower() else ".yaml"
        if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", raw, re.IGNORECASE):
            raise ValueError("Workflow filename contains unsupported characters")
        destination = str(destination or "custom").strip().lower()
        if destination == "custom":
            output_workflow = (self.repo_root / "runner" / "workflow" / "custom" / folder / raw).resolve()
            output_prompt_dir = (self.repo_root / "runner" / "prompts" / "custom" / folder).resolve()
        elif destination == "project":
            if project is None:
                raise ValueError("Open a Project before saving to Current Project")
            if "/" in folder:
                raise ValueError("Project Workflow folder must be one folder name")
            output_workflow = (project_package_workflow_dir(project, folder) / raw).resolve()
            output_prompt_dir = project_package_prompt_dir(project, folder)
        else:
            raise ValueError("Workflow destination must be project or custom")
        return raw, folder, destination, output_workflow, output_prompt_dir
    def _studio_item(self, path: Path, scope: str, kind: str, workflow_visibility: dict[str, bool] | None = None) -> dict:
        resolved = path.resolve()
        readonly = scope in SYSTEM_SCOPES
        display_name = path.name
        if scope == "custom":
            root = self._custom_asset_root(kind)
            try:
                display_name = resolved.relative_to(root).as_posix()
            except ValueError:
                pass
        item = {
            "id": self._encode_file_id(resolved, kind, scope),
            "name": path.name,
            "display_name": display_name,
            "path": str(resolved),
            "scope": scope,
            "group": "System" if readonly else ("Custom" if scope == "custom" else "Project"),
            "kind": kind,
            "readonly": readonly,
            "deletable": not readonly,
        }
        try:
            stat = resolved.stat()
            item["version"] = f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            item["version"] = ""
        if kind == "workflow":
            item.update(self._workflow_requirements(resolved))
            key = os.path.normcase(os.path.abspath(str(resolved)))
            item["hidden"] = bool(workflow_visibility.get(key, False)) if workflow_visibility is not None else self.workflow_hidden(resolved)
        return item

    @staticmethod
    def _encode_file_id(path: Path, kind: str, scope: str) -> str:
        raw = json.dumps({"path": str(path), "kind": kind, "scope": scope}, separators=(",", ":"), ensure_ascii=False)
        return raw.encode("utf-8").hex()

    def _resolve_studio_file(self, file_id: str, project: Path | None) -> tuple[Path, str, str]:
        try:
            payload = json.loads(bytes.fromhex(file_id).decode("utf-8"))
            path = Path(str(payload["path"])).resolve()
            kind = str(payload["kind"])
            scope = str(payload["scope"])
        except Exception as exc:
            raise ValueError("Invalid workflow file id") from exc
        if not path.is_file() or path.suffix.lower() not in EDITABLE_SUFFIXES:
            raise ValueError("Workflow/prompt file does not exist")

        valid = False
        if scope == "system" and kind == "workflow":
            valid = self._is_within(path, (self.repo_root / "runner" / "workflow" / "system").resolve())
        elif scope == "custom" and kind == "workflow":
            tool_root = (self.repo_root / "runner" / "workflow" / "custom").resolve()
            prompt_root = (self.repo_root / "runner" / "prompts" / "custom").resolve()
            valid = self._is_within(path, tool_root) and not self._is_within(path, prompt_root)
        elif scope == "system" and kind == "prompt":
            system_prompt_roots = (
                (self.repo_root / "runner" / "prompts" / "stages").resolve(),
                (self.repo_root / "runner" / "prompts" / "system").resolve(),
            )
            valid = any(self._is_within(path, root) for root in system_prompt_roots)
        elif scope == "custom" and kind == "prompt":
            valid = self._is_within(path, (self.repo_root / "runner" / "prompts" / "custom").resolve())
        elif scope == "project" and project is not None:
            package = project_package_for_asset(project, path)
            if package is not None:
                _folder, _package_root, workflow_dir, prompt_dir = package
                valid = self._is_within(path, workflow_dir if kind == "workflow" else prompt_dir)

        if not valid:
            raise ValueError("File is outside allowed workflow/prompt roots")
        return path, kind, scope

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()



    def _supported_stage_types(self) -> set[str]:
        tool = self.repo_root / "tool" / "workflow_catalog.py"
        if not tool.is_file():
            return {"base", "task", "review", "ai_validator", "command", "plan"}
        return set(self.workflow_catalog().get("stage_types", {}))

    def _custom_asset_root(self, kind: str) -> Path:
        kind = str(kind or "").strip().lower()
        if kind == "workflow":
            return (self.repo_root / "runner" / "workflow" / "custom").resolve()
        if kind == "prompt":
            return (self.repo_root / "runner" / "prompts" / "custom").resolve()
        raise ValueError("Custom asset kind must be workflow or prompt")

    @staticmethod
    def _is_technical_folder_part(part: str) -> bool:
        value = str(part or "").strip().lower()
        return (
            not value
            or value.startswith(".")
            or value in {"__pycache__", "__pypackages__", "node_modules"}
            or value.endswith(".egg-info")
        )

    @classmethod
    def _normalize_custom_folder(cls, folder: str) -> str:
        raw = str(folder or "").strip().replace("\\", "/")
        if not raw or raw in {".", "/"}:
            return ""
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            raise ValueError("Custom folder must be relative to the Custom root")
        parts = [part.strip() for part in raw.split("/") if part.strip()]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("Custom folder cannot contain . or ..")
        if any(cls._is_technical_folder_part(part) for part in parts):
            raise ValueError("Custom folder contains a reserved technical directory")
        if any(not re.fullmatch(r"[A-Za-z0-9_. -]+", part) for part in parts):
            raise ValueError("Custom folder contains unsupported characters")
        return "/".join(parts)

    def studio_custom_folders(self, kind: str) -> list[str]:
        root = self._custom_asset_root(kind)
        root.mkdir(parents=True, exist_ok=True)
        folders = [""]
        for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: str(p).lower()):
            rel = path.relative_to(root).as_posix()
            if rel and not any(self._is_technical_folder_part(part) for part in Path(rel).parts):
                folders.append(rel)
        return folders

    def studio_custom_folder_create(self, kind: str, folder: str) -> dict:
        with self._edit_lock:
            self._require_editable()
            rel = self._normalize_custom_folder(folder)
            if not rel:
                raise ValueError("Folder name is required")
            root = self._custom_asset_root(kind)
            target = (root / Path(rel)).resolve()
            if not self._is_within(target, root):
                raise ValueError("Custom folder is outside the Custom root")
            target.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "folder": rel, "folders": self.studio_custom_folders(kind)}

    def _workflow_visibility(self) -> dict[str, bool]:
        try:
            raw = json.loads(self.workflow_visibility_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {os.path.normcase(os.path.abspath(str(path))): bool(hidden) for path, hidden in raw.items() if str(path).strip()}

    def workflow_hidden(self, path: Path) -> bool:
        return bool(self._workflow_visibility().get(os.path.normcase(os.path.abspath(str(path.resolve()))), False))

    def studio_set_workflow_hidden(self, file_id: str, hidden: bool, project: Path | None = None) -> dict:
        with self._edit_lock:
            path, kind, scope = self._resolve_studio_file(file_id, project)
            if kind != "workflow":
                raise ValueError("Visibility can only be changed for Workflow files")
            values = self._workflow_visibility()
            key = os.path.normcase(os.path.abspath(str(path.resolve())))
            if hidden:
                values[key] = True
            else:
                values.pop(key, None)
            self._atomic_json(self.workflow_visibility_file, values)
            return self._studio_item(path, scope, kind)

    # ------------------------------ live stream helpers ------------------------------


__all__ = ["WorkflowStudioMixin"]
