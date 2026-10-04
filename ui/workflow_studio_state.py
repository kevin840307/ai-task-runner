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
import signal
import threading
import sys
import tempfile
import uuid
from pathlib import Path

import yaml
from jinja2 import Environment, meta

from project_registry import path_key

try:
    from .workflow_graph import build_workflow_graph
    from .workflow_storage import project_asset_root
except ImportError:  # direct ui/main.py execution
    from workflow_graph import build_workflow_graph
    from workflow_storage import project_asset_root


EDITABLE_SUFFIXES = {".yaml", ".yml", ".md"}


class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # noqa: ANN001
        return super().increase_indent(flow, False)


class WorkflowStudioMixin:
    # ------------------------------ workflow studio ------------------------------
    def studio_files(self, project: Path | None = None) -> dict:
        """List editable Workflow YAML and Prompt Markdown from the two asset roots."""
        scopes: list[tuple[str, Path | None]] = [("global", None)]
        if project is not None:
            scopes.append(("project", project))

        workflows: list[dict] = []
        prompts: list[dict] = []
        visibility = self._workflow_visibility()
        for scope, selected_project in scopes:
            workflow_root = self._asset_root("workflow", scope, selected_project)
            prompt_root = self._asset_root("prompt", scope, selected_project)
            if workflow_root.is_dir():
                for path in sorted(workflow_root.glob("*.yaml")) + sorted(workflow_root.glob("*.yml")):
                    workflows.append(self._studio_item(path, scope, "workflow", visibility))
            if prompt_root.is_dir():
                for path in sorted(prompt_root.rglob("*.md")):
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
        context_file = self.repo_root / "runner" / "prompting.py"
        try:
            tree = ast.parse(context_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise ValueError(f"Cannot read prompt context contract: {exc}") from exc
        paths = self._ast_dict_paths(self._ast_function_return(tree, "build_stage_prompt_context"))
        task_fields = self._ast_dict_paths(self._ast_function_return(tree, "_task_data"))
        paths.extend(f"task.{key}" for key in task_fields if "." not in key)
        return paths

    def _loader_prompt_contracts(self) -> dict[str, list[str]]:
        """Discover dedicated shared Prompt variables from literal render_prompt calls.

        `common/rules.md` is not a Stage prompt. It is rendered by the prompt
        loader with its own values. Immutable output/retry protocols live in
        runner/prompting.py and are intentionally not Studio resources.
        Parse that contract statically so Workflow Studio does not import Runner Core
        and does not show false Prompt warnings when those files are inspected.
        """
        loader_file = self.repo_root / "runner" / "prompting.py"
        prompt_root = self._global_asset_root("prompt")
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
            "plugin_rules": "Plugin-provided Runner rules used by common/rules.md.",
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
        source = str(prompt_path) if prompt_path is not None else str(self.repo_root / "runner" / "prompting.py")
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
            raw = self._normalize_studio_asset_name("workflow", name)
            scope = self._normalize_asset_scope(destination)
            root = self._asset_root("workflow", scope, project)
            root.mkdir(parents=True, exist_ok=True)
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"Workflow already exists: {target.name}")
            content = (
                "stages:\n"
                "  start:\n"
                "    type: base\n"
                "    prompt: common/execution.md\n\n"
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
        result = {
            **self._studio_item(path, scope, kind),
            "content": content,
            "hash": self._hash_text(content),
            "mtime": stat.st_mtime,
            "guard": self.edit_guard(),
        }
        if kind == "prompt":
            result["used_by"] = self._prompt_usages(path, project)
        return result

    def studio_save(self, file_id: str, content: str, expected_hash: str, project: Path | None = None) -> dict:
        with self._edit_lock:
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

            if not isinstance(fields, dict):
                raise ValueError("Stage fields must be an object")
            clean = {str(key): value for key, value in fields.items() if str(key) != "name"}
            updated = self._patch_stage_fields(content, stage_name, clean)
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

    def studio_stage_source(
        self,
        file_id: str,
        stage_name: str,
        mode: str,
        project: Path | None = None,
        *,
        fields: dict | None = None,
        source: str = "",
    ) -> dict:
        """Format/parse one Stage YAML fragment without writing the Workflow."""
        path, kind, _scope_name = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            raise ValueError("Stage source editor is available only for workflow YAML")
        data = self._load_workflow_yaml(path.read_text(encoding="utf-8"))
        stages = data.get("stages") if isinstance(data, dict) else None
        saved = stages.get(stage_name) if isinstance(stages, dict) else None
        draft = dict(fields) if isinstance(fields, dict) else None
        current = saved if isinstance(saved, dict) else draft
        if not isinstance(current, dict):
            raise ValueError(f"Stage not found: {stage_name}")

        if mode == "format":
            candidate = dict(draft) if draft is not None else dict(current)
            candidate.pop("name", None)
            candidate.pop("routes", None)
            candidate.pop("targets", None)
            return {
                "ok": True,
                "source": yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True).rstrip() + "\n",
            }

        if mode != "parse":
            raise ValueError("Stage source mode must be format or parse")
        try:
            parsed = yaml.safe_load(source) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Stage YAML is invalid: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Stage YAML must be a mapping")
        if "name" in parsed:
            raise ValueError("Stage key/name is managed by the Workflow and cannot be changed here")
        if "routes" in parsed or "targets" in parsed:
            raise ValueError("Stage routing is managed by the Routing tab and cannot be changed in Stage YAML")

        original_type = str(current.get("type") or "")
        parsed_type = str(parsed.get("type") or original_type)
        if original_type and parsed_type != original_type:
            raise ValueError("Stage type is immutable; create a new Stage to change type")
        if original_type and "type" not in parsed:
            parsed["type"] = original_type

        # Stage YAML may represent a not-yet-saved Designer Stage. Validate the
        # isolated Stage with the same Runner schema used by the production
        # Workflow loader; the complete Workflow is validated again on Save.
        try:
            from runner.workflow.schema import validate_stage
            validate_stage(stage_name, parsed)
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        return {"ok": True, "fields": parsed}

    def studio_path_test(
        self,
        file_id: str,
        stage_name: str,
        project: Path | None = None,
    ) -> dict:
        """Dry-run the saved canonical Workflow from one Stage to closure.

        This never mutates the Workflow file or production run state. It reuses
        tool/workflow_dryrun.py, which in turn uses the production loader and
        FlowEngine with mock Stage results.
        """
        path, kind, _scope_name = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            raise ValueError("Path test is available only for workflow YAML")
        data = self._load_workflow_yaml(path.read_text(encoding="utf-8"))
        stages = data.get("stages")
        if not isinstance(stages, dict) or stage_name not in stages:
            raise ValueError(f"Stage not found: {stage_name}")

        command = [
            sys.executable,
            str(self.repo_root / "tool" / "workflow_dryrun.py"),
            str(path),
            "--from-stage",
            str(stage_name),
            "--max-steps",
            "500",
            "--json",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Path test failed: {exc}") from exc

        raw = (completed.stdout or "").strip()
        payload: dict = {}
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {}
        if completed.returncode == 2 or not payload:
            detail = (completed.stderr or completed.stdout or "dry-run returned no JSON").strip()
            raise ValueError(f"Path test failed: {detail[-4000:]}")
        return {
            "ok": completed.returncode == 0 and bool(payload.get("completed")),
            "exit_code": completed.returncode,
            "from_stage": str(stage_name),
            "completed": bool(payload.get("completed")),
            "error": payload.get("error"),
            "cycle": payload.get("cycle"),
            "stage": payload.get("stage"),
            "transitions": list(payload.get("transitions") or []),
        }


    def _stage_test_runtime(self):
        lock = getattr(self, "_studio_stage_test_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._studio_stage_test_lock = lock
            self._studio_stage_test_processes = {}
            self._studio_stage_test_cancelled = set()
        return lock, self._studio_stage_test_processes, self._studio_stage_test_cancelled

    @staticmethod
    def _terminate_stage_test_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        pid = int(getattr(process, "pid", 0) or 0)
        if os.name == "nt" and pid > 0:
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                if result.returncode != 0:
                    process.kill()
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except OSError:
                    pass
            return
        try:
            if pid > 0:
                os.killpg(pid, signal.SIGTERM)
            else:
                process.terminate()
        except OSError:
            try:
                process.terminate()
            except OSError:
                return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                if pid > 0:
                    os.killpg(pid, signal.SIGKILL)
                else:
                    process.kill()
            except OSError:
                pass

    def studio_stage_test_cancel(self, test_id: str) -> dict:
        key = str(test_id or "").strip()
        if not key:
            raise ValueError("Stage test id is required")
        lock, processes, cancelled = self._stage_test_runtime()
        with lock:
            if len(cancelled) >= 64:
                cancelled.clear()
            cancelled.add(key)
            process = processes.get(key)
            if process is None:
                return {"ok": True, "cancelled": True, "pending": True}
        self._terminate_stage_test_process(process)
        return {"ok": True, "cancelled": True, "pending": False}

    def studio_stage_test(
        self,
        file_id: str,
        stage_name: str,
        input_text: str,
        project: Path | None = None,
        *,
        backend: str = "",
        probe_mode: str = "stage",
        test_scenario: str = "pass",
        graph: dict | None = None,
        test_id: str = "",
    ) -> dict:
        """Execute one Stage in a disposable Project, including unsaved graph drafts."""
        path, kind, _scope_name = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            raise ValueError("Stage test is available only for workflow YAML")
        data = self._load_workflow_yaml(path.read_text(encoding="utf-8"))
        if graph is not None:
            if not isinstance(graph, dict) or not isinstance(graph.get("stages"), list) or not isinstance(graph.get("flow"), list):
                raise ValueError("Stage test graph requires stages and flow")
            routes = graph.get("routes") or {}
            if not isinstance(routes, dict):
                raise ValueError("Stage test routes must be an object")
            stages = {}
            for row in graph["stages"]:
                if not isinstance(row, dict):
                    raise ValueError("Each Stage must be an object")
                name = str(row.get("name") or "").strip()
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name) or name in stages:
                    raise ValueError(f"Invalid or duplicate Stage key: {name}")
                config = {key: value for key, value in row.items() if key not in {"name", "routes"} and value is not None and value != ""}
                mapping = routes.get(name, row.get("routes"))
                if mapping:
                    config["routes"] = mapping
                stages[name] = config
            data = {"stages": stages, "flow": graph["flow"]}
        if stage_name not in data.get("stages", {}):
            raise ValueError(f"Stage not found: {stage_name}")

        with tempfile.TemporaryDirectory(prefix="ai-task-runner-stage-test-") as test_project:
            command = [
                sys.executable,
                str(self.repo_root / "tool" / "stage_probe.py"),
                "--project-root",
                test_project,
                "--workflow",
                str(path),
                "--stage",
                str(stage_name),
                "--request-stdin",
            ]
            if str(backend or "").strip():
                command += ["--backend", str(backend).strip()]
            payload_text = json.dumps(
                {
                    "input": input_text,
                    "workflow": data,
                    "probe_mode": str(probe_mode or "stage"),
                    "test_scenario": str(test_scenario or "pass"),
                },
                ensure_ascii=False,
            )
            key = str(test_id or "").strip() or uuid.uuid4().hex
            lock, processes, cancelled = self._stage_test_runtime()
            popen_kwargs = {
                "cwd": str(self.repo_root),
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True
            try:
                process = subprocess.Popen(command, **popen_kwargs)
            except OSError as exc:
                raise ValueError(f"Stage test failed: {exc}") from exc

            cancel_immediately = False
            with lock:
                processes[key] = process
                if key in cancelled:
                    cancelled.discard(key)
                    cancel_immediately = True
            if cancel_immediately:
                self._terminate_stage_test_process(process)

            try:
                stdout, stderr = process.communicate(payload_text, timeout=900)
            except subprocess.TimeoutExpired as exc:
                self._terminate_stage_test_process(process)
                raise ValueError("Stage test timed out after 900 seconds") from exc
            finally:
                with lock:
                    was_cancelled = key in cancelled
                    processes.pop(key, None)
                    cancelled.discard(key)

            if was_cancelled or cancel_immediately:
                return {"ok": False, "cancelled": True, "test_id": key}
            completed = subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)

            raw = (completed.stdout or "").strip().splitlines()
            payload = {}
            if raw:
                try:
                    payload = json.loads(raw[-1])
                except json.JSONDecodeError:
                    payload = {}
            if completed.returncode != 0 and not payload:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise ValueError("Stage test failed: " + detail[-6000:])
            if not isinstance(payload, dict):
                raise ValueError("Stage test returned invalid output")
            if payload.get("error") and not payload.get("stage"):
                raise ValueError(str(payload.get("error")))
            return payload

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
            # AI profile defaults are catalog/runtime-owned. Only validate a Prompt
            # when the user explicitly overrides the profile default.
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
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("Workflow validation failed: " + output[-12000:]) from exc
            if payload.get("valid") is not True:
                raise ValueError("Workflow validation failed: " + output[-12000:])
            # Save validates the canonical graph/schema. A workflow may intentionally
            # stop on PASS/FAIL, so matrix closure is diagnostic rather than a write
            # requirement. Invalid loaders/routes still fail before this point.
            return {
                "ok": True,
                "output": output,
                "payload": payload,
                "warning": "" if payload.get("closed") else "Workflow has non-closing paths.",
            }
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _require_studio_writable(self, scope: str) -> None:
        if scope not in {"global", "project"}:
            raise ValueError("Unknown Workflow asset scope")

    def _workflow_requirements(self, path: Path | None) -> dict:
        result = {"requires_python_validator": False, "has_ai_validator": False}
        if path is None or not path.is_file():
            return result
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return result
        stages = data.get("stages") if isinstance(data, dict) else {}
        if not isinstance(stages, dict):
            return result
        for cfg in stages.values():
            if not isinstance(cfg, dict):
                continue
            stage_type = str(cfg.get("type") or "base")
            if stage_type == "ai_validator":
                result["has_ai_validator"] = True
            command = cfg.get("command")
            command_text = " ".join(command) if isinstance(command, list) else str(command or "")
            if (
                stage_type == "command"
                and str(cfg.get("result_kind") or "") == "validation"
                and "{validator}" in command_text
            ):
                result["requires_python_validator"] = True
        return result

    def _resolve_prompt_reference(
        self, workflow_path: Path, reference: str
    ) -> Path | None:
        value = str(reference or "").strip()
        if not value:
            return None
        raw = Path(value).expanduser()
        candidates = [raw] if raw.is_absolute() else [
            workflow_path.parent / raw,
            workflow_path.parent.parent / "prompts" / raw,
            self._global_asset_root("prompt") / raw,
        ]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_file() and resolved.suffix.lower() == ".md":
                return resolved
        return None

    def _effective_stage_prompt_reference(self, config: dict) -> str:
        prompt = str(config.get("prompt") or "").strip()
        if prompt:
            return prompt
        stage_type = str(config.get("type") or "base")
        catalog = (self.workflow_catalog().get("stage_types") or {}).get(stage_type) or {}
        if stage_type == "base":
            profile = str(config.get("profile") or "generic")
            defaults = ((catalog.get("profiles") or {}).get(profile) or {}).get("defaults") or {}
            return str(defaults.get("prompt") or "").strip()
        for option in catalog.get("options") or []:
            if option.get("name") == "prompt":
                return str(option.get("default") or "").strip()
        return ""

    def _workflow_prompt_refs(self, content: str) -> list[tuple[str, str]]:
        data = self._load_workflow_yaml(content)
        stages = data.get("stages") or {}
        refs: list[tuple[str, str]] = []
        if not isinstance(stages, dict):
            return refs
        for name, config in stages.items():
            if not isinstance(config, dict):
                continue
            stage_type = str(config.get("type") or "base")
            effective_prompt = self._effective_stage_prompt_reference(config)
            if stage_type == "base" and not effective_prompt:
                refs.append((str(name), "<required>"))
            elif effective_prompt:
                refs.append((str(name), effective_prompt))
            continuation = config.get("continuation_prompt")
            if isinstance(continuation, str) and continuation.strip():
                refs.append((str(name), continuation.strip()))
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
        roots = [self._global_asset_root("workflow")]
        known_projects = [
            Path(row["path"]).absolute()
            for row in self.projects()
            if row.get("exists")
        ]
        if project is not None:
            project_path = Path(project).absolute()
            if all(path_key(project_path) != path_key(item) for item in known_projects):
                known_projects.append(project_path)
        roots.extend(project_asset_root(item, "workflow") for item in known_projects)

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
            raw = self._normalize_studio_asset_name("prompt", name)
            scope = self._normalize_asset_scope(destination)
            root = self._asset_root("prompt", scope, project)
            root.mkdir(parents=True, exist_ok=True)
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"Prompt already exists: {raw}")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write("# Prompt\n\n{{ goal }}\n")
            item = self._studio_item(target, scope, "prompt")
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_delete(self, file_id: str, project: Path | None = None) -> dict:
        with self._edit_lock:
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
        if kind == "workflow":
            if "/" in raw or "\\" in raw or raw in {".", ".."}:
                raise ValueError("Workflow name must be a file name, not a path")
            if not raw.lower().endswith((".yaml", ".yml")):
                raw += ".workflow.yaml" if "workflow" not in raw.lower() else ".yaml"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", raw, re.IGNORECASE):
                raise ValueError("Workflow file name contains unsupported characters")
        elif kind == "prompt":
            raw = raw.replace("\\", "/")
            if not raw.lower().endswith(".md"):
                raw += ".md"
            prompt_path = Path(raw)
            if len(prompt_path.parts) == 1:
                prompt_path = Path("common") / prompt_path
            if prompt_path.is_absolute() or any(part in {"", ".", ".."} for part in prompt_path.parts):
                raise ValueError("Prompt name must be a safe relative path")
            if any(
                not re.fullmatch(r"[A-Za-z0-9_. -]+", part, re.IGNORECASE)
                for part in prompt_path.parts[:-1]
            ) or not re.fullmatch(r"[A-Za-z0-9_. -]+\.md", prompt_path.name, re.IGNORECASE):
                raise ValueError("Prompt path contains unsupported characters")
            raw = prompt_path.as_posix()
        else:
            raise ValueError("Unsupported Studio asset kind")
        return raw

    def _studio_scope_root(
        self, kind: str, scope: str, project: Path | None
    ) -> Path:
        root = self._asset_root(kind, scope, project)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def studio_rename(
        self,
        file_id: str,
        name: str,
        project: Path | None = None,
    ) -> dict:
        with self._edit_lock:
            path, kind, scope = self._resolve_studio_file(file_id, project)
            if kind == "prompt":
                usages = self._prompt_usages(path, project)
                if usages:
                    raise ValueError(
                        "Prompt is still referenced; update Workflow references before rename: "
                        + "; ".join(usages[:12])
                    )
            raw = self._normalize_studio_asset_name(kind, name)
            root = self._asset_root(kind, scope, project)
            target = (root / raw).resolve()
            if target == path:
                item = self._studio_item(path, scope, kind)
                return {"item": item, "file": self.studio_read(item["id"], project)}
            if target.exists():
                raise ValueError(f"{kind.title()} already exists: {raw}")
            target.parent.mkdir(parents=True, exist_ok=True)
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
            path, kind, scope = self._resolve_studio_file(file_id, project)
            raw = self._normalize_studio_asset_name(kind, name)
            root = self._asset_root(kind, scope, project)
            root.mkdir(parents=True, exist_ok=True)
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"{kind.title()} already exists: {raw}")
            target.parent.mkdir(parents=True, exist_ok=True)
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

    def studio_graph_save(
        self,
        file_id: str,
        graph: dict,
        expected_hash: str,
        project: Path | None = None,
    ) -> dict:
        """Validate and persist one complete Flow UI draft.

        YAML remains canonical. START/END are UI-only nodes and never enter the
        Workflow file. The Designer may connect, retarget or delete PASS/FAIL/HANDOFF
        edges freely. Flow order is only the compact representation for a connected
        PASS-to-next edge; graph save validates the complete draft before writing YAML.
        """
        with self._edit_lock:
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if kind != "workflow":
                raise ValueError("Graph editing is available only for Workflow YAML")

            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            data = self._load_workflow_yaml(content)
            stages = data.get("stages")
            if not isinstance(stages, dict):
                raise ValueError("Workflow stages must be a mapping")
            if not isinstance(graph, dict):
                raise ValueError("Graph must be an object")

            draft_rows = graph.get("stages")
            desired: dict[str, dict] | None = None
            if draft_rows is not None:
                if not isinstance(draft_rows, list):
                    raise ValueError("Graph stages must be a list")
                desired = {}
                for row in draft_rows:
                    if not isinstance(row, dict):
                        raise ValueError("Each Graph Stage must be an object")
                    name = str(row.get("name") or "").strip()
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
                        raise ValueError(f"Invalid Stage key: {name}")
                    if name in desired:
                        raise ValueError(f"Duplicate Graph Stage: {name}")
                    config = {key: value for key, value in row.items() if key != "name"}
                    desired[name] = config
                if not desired:
                    raise ValueError("Workflow must contain at least one Stage")
            stage_names = set(desired) if desired is not None else set(stages)

            raw_flow = graph.get("flow")
            if not isinstance(raw_flow, list):
                raise ValueError("Graph flow must be a list")
            flow = [str(name).strip() for name in raw_flow if str(name).strip()]
            if len(flow) != len(set(flow)):
                raise ValueError("Workflow flow cannot contain duplicate Stage names")
            unknown_flow = [name for name in flow if name not in stage_names]
            if unknown_flow:
                raise ValueError("Workflow flow references unknown Stage: " + ", ".join(unknown_flow))

            raw_routes = graph.get("routes") or {}
            if not isinstance(raw_routes, dict):
                raise ValueError("Graph routes must be an object")
            normalized_routes: dict[str, dict[str, str]] = {}
            targets = stage_names | {"next", "done", "stop"}
            for stage_name, mapping in raw_routes.items():
                stage_name = str(stage_name)
                if stage_name not in stage_names:
                    raise ValueError(f"Graph routes reference unknown Stage: {stage_name}")
                if mapping in (None, {}):
                    continue
                if not isinstance(mapping, dict):
                    raise ValueError(f"Graph routes for {stage_name} must be an object")
                clean: dict[str, str] = {}
                for status, target in mapping.items():
                    status = str(status).lower().strip()
                    target = str(target).strip()
                    if status not in {"pass", "fail"}:
                        raise ValueError(f"Unsupported result edge status: {status}")
                    if target not in targets:
                        raise ValueError(f"Graph route {stage_name}.{status} references unknown target: {target}")
                    clean[status] = target
                if clean:
                    normalized_routes[stage_name] = clean

            updated = content
            if desired is not None:
                for name in stages:
                    if name not in desired:
                        updated = self._remove_stage_definition_block(updated, name)
                for name, config in desired.items():
                    original = stages.get(name)
                    if not isinstance(original, dict):
                        clean = {key: value for key, value in config.items() if key != "routes" and value not in (None, "")}
                        updated = self._insert_stage_block(updated, name, clean)
                        continue
                    changes = {}
                    for key, value in config.items():
                        if key in {"name", "routes"}:
                            continue
                        previous = original.get(key, "" if key in {"status", "prompt"} else None)
                        if value != previous:
                            changes[key] = None if key in {"status", "prompt", "label"} and value == "" else value
                    if changes:
                            updated = self._patch_stage_fields(updated, name, changes)
            updated = self._replace_flow_block(updated, flow)
            # Patch every Stage so deleting an Edge removes the YAML route too.
            for stage_name in (desired if desired is not None else stages):
                updated = self._patch_stage_fields(
                    updated,
                    str(stage_name),
                    {"routes": normalized_routes.get(str(stage_name))},
                )

            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            file = self.studio_read(file_id, project)
            return {
                "file": file,
                "visual": self.studio_visual(file_id, project),
                "graph": build_workflow_graph(self._load_workflow_yaml(file["content"])),
            }

    def studio_import(
        self,
        kind: str,
        name: str,
        content: str,
        destination: str,
        project: Path | None = None,
    ) -> dict:
        with self._edit_lock:
            kind = str(kind or "").strip().lower()
            if kind not in {"workflow", "prompt"}:
                raise ValueError("Import kind must be workflow or prompt")
            scope = self._normalize_asset_scope(destination)
            root = self._asset_root(kind, scope, project)
            root.mkdir(parents=True, exist_ok=True)
            raw = self._normalize_studio_asset_name(kind, name or f"imported-{kind}")
            target = (root / raw).resolve()
            if target.exists():
                raise ValueError(f"Asset already exists: {raw}")
            target.parent.mkdir(parents=True, exist_ok=True)
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

    def _global_asset_root(self, kind: str) -> Path:
        name = "workflows" if kind == "workflow" else "prompts" if kind == "prompt" else ""
        if not name:
            raise ValueError("asset kind must be workflow or prompt")
        return (self.repo_root / "runner" / "assets" / name).resolve()

    @staticmethod
    def _normalize_asset_scope(value: str) -> str:
        scope = str(value or "global").strip().lower()
        if scope not in {"global", "project"}:
            raise ValueError("Asset destination must be global or project")
        return scope

    def _asset_package_root(self, scope: str, project: Path | None) -> Path:
        scope = self._normalize_asset_scope(scope)
        if scope == "global":
            return (self.repo_root / "runner" / "assets").resolve()
        if project is None:
            raise ValueError("Select a Project before using Project assets")
        return (project.resolve() / ".ai-task-runner" / "assets").resolve()

    def _asset_root(self, kind: str, scope: str, project: Path | None) -> Path:
        package = self._asset_package_root(scope, project)
        name = "workflows" if kind == "workflow" else "prompts" if kind == "prompt" else ""
        if not name:
            raise ValueError("asset kind must be workflow or prompt")
        return (package / name).resolve()

    def _workflow_output_paths(
        self,
        project: Path | None,
        folder: str,
        filename: str,
        destination: str,
    ) -> tuple[str, str, str, Path, Path]:
        del folder
        raw = self._normalize_studio_asset_name("workflow", filename)
        scope = self._normalize_asset_scope(destination)
        workflow_root = self._asset_root("workflow", scope, project)
        workflow_root.mkdir(parents=True, exist_ok=True)
        output = (workflow_root / raw).resolve()
        return raw, "", scope, output, self._asset_package_root(scope, project)

    def _studio_item(
        self,
        path: Path,
        scope: str,
        kind: str,
        workflow_visibility: dict[str, bool] | None = None,
    ) -> dict:
        resolved = path.resolve()
        prompt_key = ""
        if kind == "prompt":
            for parent in resolved.parents:
                if parent.name == "prompts" and parent.parent.name == "assets":
                    prompt_key = resolved.relative_to(parent).as_posix()
                    break
        item = {
            "id": self._encode_file_id(resolved, kind, scope),
            "name": path.name,
            "display_name": prompt_key or path.name,
            "reference": prompt_key or path.name,
            "path": str(resolved),
            "scope": scope,
            "group": "Global" if scope == "global" else "Project",
            "kind": kind,
            "readonly": False,
            "deletable": True,
        }
        try:
            stat = resolved.stat()
            item["version"] = f"{stat.st_mtime_ns}:{stat.st_size}"
            item["mtime"] = stat.st_mtime
        except OSError:
            item["version"] = ""
            item["mtime"] = 0
        if kind == "workflow":
            item.update(self._workflow_requirements(resolved))
            key = os.path.normcase(os.path.abspath(str(resolved)))
            item["hidden"] = (
                bool(workflow_visibility.get(key, False))
                if workflow_visibility is not None
                else self.workflow_hidden(resolved)
            )
        return item

    @staticmethod
    def _encode_file_id(path: Path, kind: str, scope: str) -> str:
        raw = json.dumps({"path": str(path), "kind": kind, "scope": scope}, separators=(",", ":"), ensure_ascii=False)
        return raw.encode("utf-8").hex()

    def _resolve_studio_file(
        self, file_id: str, project: Path | None
    ) -> tuple[Path, str, str]:
        try:
            payload = json.loads(bytes.fromhex(file_id).decode("utf-8"))
            path = Path(str(payload["path"])).resolve()
            kind = str(payload["kind"])
            scope = self._normalize_asset_scope(str(payload["scope"]))
        except Exception as exc:
            raise ValueError("Invalid workflow file id") from exc
        if kind not in {"workflow", "prompt"}:
            raise ValueError("Invalid Workflow asset kind")
        if not path.is_file() or path.suffix.lower() not in EDITABLE_SUFFIXES:
            raise ValueError("Workflow/prompt file does not exist")
        root = self._asset_root(kind, scope, project).resolve()
        if kind == "workflow":
            if path.parent != root:
                raise ValueError("Workflow must live directly in the Workflow asset root")
        elif not self._is_within(path, root):
            raise ValueError("Prompt is outside allowed Prompt asset root")
        if kind == "workflow" and path.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("Workflow asset must be YAML")
        if kind == "prompt" and path.suffix.lower() != ".md":
            raise ValueError("Prompt asset must be Markdown")
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
            return {"base", "ai_validator", "command", "plan", "handoff"}
        return set(self.workflow_catalog().get("stage_types", {}))

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
