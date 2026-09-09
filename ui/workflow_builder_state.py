from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import uuid
import yaml
from pathlib import Path

try:
    from .workflow_storage import project_package_prompt_dir, project_package_workflow_dir
    from .server_support import background_process_kwargs
except ImportError:
    from workflow_storage import project_package_prompt_dir, project_package_workflow_dir
    from server_support import background_process_kwargs

RUNTIME_DIR = ".ai-task-runner"


class WorkflowBuilderMixin:
    def _builder_root(self) -> Path:
        """UI-owned Workflow Builder workspace, independent from every user Project."""
        return (self.ui_root / "data" / "workflow-builder").resolve()

    def _builder_active_path(self) -> Path:
        return self._builder_root() / "active.json"

    def _builder_set_active(self, job_id: str) -> None:
        self._atomic_json(self._builder_active_path(), {
            "schema_version": 1,
            "job_id": str(job_id),
            "updated_at": time.time(),
        })

    def _builder_clear_active(self, job_id: str = "") -> None:
        path = self._builder_active_path()
        if not path.is_file():
            return
        if job_id:
            current = self._read_json(path) or {}
            if str(current.get("job_id") or "") != str(job_id):
                return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _builder_active_job_id(self) -> str:
        payload = self._read_json(self._builder_active_path()) or {}
        job_id = str(payload.get("job_id") or "").strip()
        if not re.fullmatch(r"[a-f0-9]{12}", job_id):
            self._builder_clear_active()
            return ""
        if not self._builder_job_root(job_id).is_dir():
            self._builder_clear_active(job_id)
            return ""
        return job_id

    def _builder_job_root(self, job_id: str) -> Path:
        value = str(job_id or "").strip()
        if not re.fullmatch(r"[a-f0-9]{12}", value):
            raise ValueError("Invalid Workflow Builder job id")
        root = self._builder_root()
        path = (root / value).resolve()
        if not self._is_within(path, root):
            raise ValueError("Workflow Builder job is outside the UI draft root")
        return path

    @staticmethod
    def _tail_text(path: Path, limit: int = 12000) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-max(1, int(limit)):].strip()

    def studio_draft_info(self) -> dict:
        builder_root = self.repo_root / "workflow_builder"
        builder = builder_root / "run.py"
        workflow = builder_root / "workflow_builder.yaml"
        prompt = builder_root / "prompt.md"
        validator = builder_root / "validation.py"
        publisher = builder_root / "publish.py"
        available = all(path.is_file() for path in (builder, workflow, prompt, validator, publisher))
        workspace_root = self._builder_root()
        return {
            "available": available,
            "builder": str(builder),
            "workflow": str(workflow),
            "prompt": str(prompt),
            "validator": str(validator),
            "publisher": str(publisher),
            "workspace_root": str(workspace_root),
            "workspace_pattern": str(workspace_root / "<new-job-id>"),
            "message": "AI Workflow Builder is ready." if available else "AI Workflow Builder files are incomplete.",
        }

    def studio_generate_workflow(
        self,
        request: str,
        backend: str = "",
        folder: str = "",
        filename: str = "",
    ) -> dict:
        """Start a brand-new validated draft job in the UI-owned workspace.

        Workflow generation is deliberately independent from the selected Project.
        The Builder Runner receives the job directory itself as its isolated
        ``--project-root`` so generation also works when no Project exists.
        Generate never creates a real Workflow asset; Save is the publish boundary.
        """
        with self._builder_lock:
            info = self.studio_draft_info()
            if not info.get("available"):
                raise ValueError(info.get("message") or "AI Workflow Builder is unavailable")
            request = str(request or "").strip()
            if not request:
                raise ValueError("Workflow requirements are required")
            folder = self._normalize_workflow_folder(folder)
            filename = str(filename or "").strip()
            if not filename:
                raise ValueError("Workflow filename is required")
            if "/" in filename or "\\" in filename or filename in {".", ".."}:
                raise ValueError("Workflow filename must be a file name, not a path")
            if not filename.lower().endswith((".yaml", ".yml")):
                filename += ".workflow.yaml" if "workflow" not in filename.lower() else ".yaml"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", filename, re.IGNORECASE):
                raise ValueError("Workflow filename contains unsupported characters")

            base = self._builder_root()
            base.mkdir(parents=True, exist_ok=True)

            # Exactly one Generator job may exist at a time. Browser refresh/close does
            # not own the lifecycle; active.json does. If a job already exists, return
            # it instead of accidentally launching a second AI run.
            active_job_id = self._builder_active_job_id()
            if active_job_id:
                active = self.studio_generate_status(active_job_id)
                if active.get("state") == "cancelled":
                    shutil.rmtree(self._builder_job_root(active_job_id), ignore_errors=True)
                    self._builder_clear_active(active_job_id)
                else:
                    return {**active, "ok": True, "existing": True}

            # Terminal, unregistered leftovers are disposable. Never remove active.json
            # here; it is the single source of truth for the current Generator job.
            for job in list(base.iterdir()):
                if job.is_dir():
                    shutil.rmtree(job, ignore_errors=True)

            job_id = uuid.uuid4().hex[:12]
            job_root = self._builder_job_root(job_id)
            job_root.mkdir(parents=True, exist_ok=False)
            status = {
                "schema_version": 1,
                "job_id": job_id,
                "state": "queued",
                "message": "Preparing Workflow Builder",
                "request": request,
                "backend": str(backend or ""),
                "folder": folder,
                "filename": filename,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._atomic_json(job_root / "status.json", status)
            self._builder_set_active(job_id)
            command = [
                sys.executable,
                str(self.repo_root / "workflow_builder" / "run.py"),
                # The job itself is an isolated temporary Runner project. It is not
                # the currently selected user Project and does not require one.
                "--project-root", str(job_root),
                "--request", request,
                "--draft-only",
                "--job-dir", str(job_root),
            ]
            if backend:
                command += ["--backend", backend]
            process_log = job_root / "builder-process.log"
            kwargs = background_process_kwargs()
            kwargs["cwd"] = str(self.repo_root)
            # Keep startup diagnostics.  A child can fail before workflow_builder/run.py
            # gets far enough to update status.json (for example an import error).
            # In that case the UI can report the real traceback instead of the vague
            # "process stopped unexpectedly" message.
            kwargs.pop("stdout", None)
            kwargs.pop("stderr", None)
            try:
                with process_log.open("w", encoding="utf-8", errors="replace") as stream:
                    process = self._process_module.Popen(command, stdout=self._process_module.DEVNULL, stderr=stream, **kwargs)
                status.update({
                    "pid": int(process.pid),
                    "process_log": str(process_log),
                    "message": "Workflow Builder started",
                    "updated_at": time.time(),
                })
                self._atomic_json(job_root / "status.json", status)
            except Exception as exc:
                status.update({"state": "failed", "message": str(exc), "process_log": str(process_log), "updated_at": time.time()})
                self._atomic_json(job_root / "status.json", status)
                raise
            return {"ok": True, "job_id": job_id, "state": "queued", "message": "Workflow Builder started. No Workflow has been created yet.", "workspace": str(job_root), "folder": folder, "filename": filename}

    def studio_generate_active(self) -> dict:
        """Return the single active Generator job so a reopened UI can resume it."""
        with self._builder_lock:
            job_id = self._builder_active_job_id()
            if not job_id:
                return {"ok": True, "active": False, "workspace_root": str(self._builder_root())}
            payload = self.studio_generate_status(job_id)
            if payload.get("state") == "cancelled":
                shutil.rmtree(self._builder_job_root(job_id), ignore_errors=True)
                self._builder_clear_active(job_id)
                return {"ok": True, "active": False, "workspace_root": str(self._builder_root())}
            status = self._read_json(self._builder_job_root(job_id) / "status.json") or {}
            return {
                **payload,
                "active": True,
                "request": str(status.get("request") or ""),
                "backend": str(status.get("backend") or ""),
                "folder": str(status.get("folder") or ""),
                "filename": str(status.get("filename") or ""),
                "workspace": str(self._builder_job_root(job_id)),
            }

    def _builder_paths(self, job_root: Path, status: dict) -> tuple[Path, Path, dict]:
        result = status.get("result") if isinstance(status.get("result"), dict) else (self._read_json(job_root / "result.json") or {})
        workflow = Path(str(result.get("draft_workflow") or job_root / "draft" / "workflow.yaml")).resolve()
        prompts = Path(str(result.get("draft_prompt_dir") or job_root / "draft" / "prompts")).resolve()
        if not self._is_within(workflow, job_root) or not self._is_within(prompts, job_root):
            raise ValueError("Workflow Builder draft paths are invalid")
        return workflow, prompts, result

    @staticmethod
    def _builder_visual(workflow_text: str) -> dict:
        try:
            data = yaml.safe_load(workflow_text) or {}
        except yaml.YAMLError:
            return {"stages": [], "flow": []}
        stages = data.get("stages") if isinstance(data, dict) and isinstance(data.get("stages"), dict) else {}
        flow = data.get("flow") if isinstance(data, dict) and isinstance(data.get("flow"), list) else []
        rows = []
        for name, cfg in stages.items():
            cfg = cfg if isinstance(cfg, dict) else {}
            rows.append({"name": str(name), "type": str(cfg.get("type") or "base"), "status": str(cfg.get("status") or ""), "prompt": str(cfg.get("prompt") or "")})
        return {"stages": rows, "flow": flow}

    def _builder_preview(self, job_root: Path, status: dict) -> dict:
        workflow, prompts, result = self._builder_paths(job_root, status)
        if not workflow.is_file():
            raise ValueError("Workflow Builder draft Workflow is missing")
        workflow_text = workflow.read_text(encoding="utf-8", errors="replace")[:240000]
        rows: list[dict] = []
        if prompts.is_dir():
            for path in sorted(p for p in prompts.rglob("*") if p.is_file())[:30]:
                rows.append({"name": path.relative_to(prompts).as_posix(), "content": path.read_text(encoding="utf-8", errors="replace")[:120000]})
        return {"workflow": workflow_text, "prompts": rows, "validation": str(result.get("validation") or "")[-12000:], "visual": self._builder_visual(workflow_text)}

    def _builder_apply_edits(self, job_root: Path, status: dict, workflow_content: str | None, prompt_rows: object) -> tuple[Path, Path]:
        workflow, prompts, _ = self._builder_paths(job_root, status)
        if workflow_content is not None:
            workflow.write_text(str(workflow_content), encoding="utf-8")
        if isinstance(prompt_rows, list):
            for row in prompt_rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip().replace("\\", "/")
                if not name or name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError("Invalid generated Prompt name")
                target = (prompts / name).resolve()
                if not self._is_within(target, prompts):
                    raise ValueError("Generated Prompt is outside the draft Prompt directory")
                if not target.is_file():
                    raise ValueError(f"Generated Prompt not found: {name}")
                content = str(row.get("content") or "")
                check = self._check_prompt_content(content, target)
                if not check.get("ok"):
                    raise ValueError(f"Prompt validation failed ({name}): {check.get('summary')}")
                target.write_text(content, encoding="utf-8")
        return workflow, prompts

    def _builder_validate_draft(self, job_root: Path, workflow: Path, prompts: Path) -> dict:
        command = [sys.executable, str(self.repo_root / "workflow_builder" / "validation.py"), "--project-root", str(job_root), "--draft-workflow", str(workflow), "--draft-prompt-dir", str(prompts)]
        result = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=60)
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            raise ValueError("Workflow draft validation failed: " + output[-12000:])
        return {"ok": True, "output": output[-12000:]}

    def studio_generate_status(self, job_id: str) -> dict:
        job_root = self._builder_job_root(job_id)
        status = self._read_json(job_root / "status.json")
        if not status:
            raise ValueError("Workflow Builder draft was not found")
        state = str(status.get("state") or "queued")
        pid = int(status.get("pid") or 0)
        if state in {"queued", "running", "cancelling"}:
            age = max(0.0, time.time() - float(status.get("updated_at") or status.get("created_at") or time.time()))
            stale = (pid and not self._pid_alive(pid)) or (not pid and age >= 30)
            if stale:
                terminal = "cancelled" if state == "cancelling" else "failed"
                if terminal == "cancelled":
                    message = "Workflow generation cancelled"
                else:
                    process_log = Path(str(status.get("process_log") or job_root / "builder-process.log"))
                    diagnostic = self._tail_text(process_log, 6000)
                    message = "Workflow Builder process stopped unexpectedly"
                    if diagnostic:
                        message += ": " + diagnostic
                status.update({"state": terminal, "message": message, "updated_at": time.time()})
                self._atomic_json(job_root / "status.json", status)
                state = terminal
        if state in {"ready", "failed", "cancelled"} and not status.get("runtime_cleared"):
            # Only the isolated Builder runtime is disposable. Never reset or stop a
            # user Project as a side effect of Workflow generation.
            shutil.rmtree(job_root / RUNTIME_DIR, ignore_errors=True)
            status["runtime_cleared"] = True
            status["updated_at"] = time.time()
            self._atomic_json(job_root / "status.json", status)
        payload = {"ok": state != "failed", "job_id": job_id, "state": state, "message": str(status.get("message") or state), "workspace": str(job_root)}
        if state == "ready":
            payload["draft"] = self._builder_preview(job_root, status)
        return payload

    def studio_generate_validate(self, job_id: str, workflow_content: str | None, prompt_rows: object) -> dict:
        with self._builder_lock:
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            if status.get("state") != "ready":
                raise ValueError("Workflow Builder draft is not ready to validate")
            workflow, prompts = self._builder_apply_edits(job_root, status, workflow_content, prompt_rows)
            result = self._builder_validate_draft(job_root, workflow, prompts)
            status["message"] = "Draft validation passed"
            status["updated_at"] = time.time()
            self._atomic_json(job_root / "status.json", status)
            result["draft"] = self._builder_preview(job_root, status)
            return result

    def studio_generate_save(self, project: Path | None, job_id: str, folder: str, filename: str, destination: str, workflow_content: str | None = None, prompt_rows: object = None) -> dict:
        with self._builder_lock, self._edit_lock:
            # Publishing mutates a real Workflow/Prompt asset, so keep the existing
            # global edit guard here even though draft generation itself is independent.
            self._require_editable()
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            if status.get("state") != "ready":
                raise ValueError("Workflow Builder draft is not ready to Save")
            raw, folder, destination, output_workflow, output_prompt_dir = self._workflow_output_paths(project, folder, filename, destination)
            if output_workflow.exists():
                raise ValueError(f"Workflow already exists: {output_workflow.name}")
            draft_workflow, draft_prompt_dir = self._builder_apply_edits(job_root, status, workflow_content, prompt_rows)
            self._builder_validate_draft(job_root, draft_workflow, draft_prompt_dir)
            command = [sys.executable, str(self.repo_root / "workflow_builder" / "publish.py"), "--project-root", str(job_root), "--draft-workflow", str(draft_workflow), "--draft-prompt-dir", str(draft_prompt_dir), "--output-workflow", str(output_workflow), "--output-prompt-dir", str(output_prompt_dir)]
            result_process = self._process_module.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=75)
            if result_process.returncode != 0:
                raise ValueError("Workflow draft publish failed: " + (result_process.stdout or result_process.stderr or "")[-12000:])
            scope = "custom" if destination == "custom" else "project"
            item = self._studio_item(output_workflow, scope, "workflow")
            file_data = self.studio_read(item["id"], project)
            shutil.rmtree(job_root, ignore_errors=True)
            self._builder_clear_active(job_id)
            return {"ok": True, "workflow": str(output_workflow), "prompt_dir": str(output_prompt_dir), "folder": folder, "item": item, "file": file_data, "message": f"Workflow {folder}/{raw} saved"}

    def studio_generate_cancel(self, job_id: str) -> dict:
        with self._builder_lock:
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            state = str(status.get("state") or "")
            if state not in {"queued", "running", "cancelling"}:
                return {"ok": True, "state": state or "cancelled"}
            (job_root / "cancel.request").write_text("cancel\n", encoding="utf-8")
            runtime = job_root / RUNTIME_DIR
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "stop.request").write_text("stop\n", encoding="utf-8")
            status.update({"state": "cancelling", "message": "Cancelling Workflow generation…", "updated_at": time.time()})
            self._atomic_json(job_root / "status.json", status)
            return {"ok": True, "state": "cancelling", "message": "Cancelling Workflow generation…"}

    def studio_generate_discard(self, job_id: str) -> dict:
        with self._builder_lock:
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            if status.get("state") in {"queued", "running", "cancelling"}:
                raise ValueError("Cancel the running Workflow generation before Discard")
            shutil.rmtree(job_root, ignore_errors=True)
            self._builder_clear_active(job_id)
            return {"ok": True, "message": "Workflow draft discarded"}



__all__ = ["WorkflowBuilderMixin"]
