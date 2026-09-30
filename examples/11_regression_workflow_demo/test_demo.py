from __future__ import annotations
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("AI_TASK_RUNNER_SOURCE_ROOT", HERE.parents[1])).resolve()

def main() -> int:
    with tempfile.TemporaryDirectory(prefix="runner-regression-demo-") as tmp:
        project = Path(tmp) / "project"
        shutil.copytree(HERE / "project", project)
        command = f'"{sys.executable}" "{HERE / "mock_agent.py"}"'
        result = subprocess.run([
            sys.executable, str(ROOT / "ai_task_runner.py"),
            "--goal-file", str(project / "prompt.md"),
            "--project-root", str(project),
            "--workflow", str(HERE / "workflow.yaml"),
            "--validator", "ai", "--backend", "qwen",
            "--command", command, "--force-new",
            "--retry-delay", "0", "--retry-max-delay", "0",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        if result.returncode:
            print(result.stdout); return result.returncode
        calls = [json.loads(x) for x in (project / ".ai-task-runner/demo-calls.jsonl").read_text(encoding="utf-8").splitlines()]
        writers = [x for x in calls if x["role"] == "writer"]
        reviews = [x for x in calls if x["role"] == "review"]
        grills = [x for x in calls if x["role"] == "grill"]
        finals = [x for x in calls if x["role"] == "final"]
        assert writers and not writers[0]["resumed"] and all(x["session"] == "writer-session" for x in writers)
        assert all(x["resumed"] for x in writers[1:])
        # Review Stages share the review client/session by default. The first call
        # establishes the contract; later review nodes continue the same session.
        assert len(reviews) == 6 and not reviews[0]["resumed"]
        assert all(x["session"] == "review-session" for x in reviews)
        # Backend transport may or may not expose --resume. The stable contract
        # is one shared session identity plus Runner-owned continuation context.
        assert any(x["shared_control"] for x in reviews[1:])
        assert all(x["full_review_contract"] for x in reviews)
        # Grill opts into a fresh session on every Stage start.
        assert len(grills) == 3 and all(not x["resumed"] for x in grills)
        assert all(x["session"] == "grill-session" for x in grills)
        assert all(x["full_grill_contract"] for x in grills)
        fixes = [x for x in writers if x["kind"] == "fix"]
        assert fixes and all(x["has_previous_data"] for x in fixes)
        assert len(finals) == 5 and all(not x["resumed"] for x in finals) and len({x["session"] for x in finals}) == 5
        assert json.loads((project / ".ai-task-runner/state.json").read_text(encoding="utf-8"))["completed"] is True
        for rel in ("artifacts/project_discovery.md","artifacts/project_documentation.md","artifacts/e2e_spec.md","artifacts/verification_design.md","regression/cases.yaml","artifacts/qualification.md"):
            assert (project / rel).is_file(), rel
        print("PASS regression workflow demo: result routing, shared continuation feedback, and fresh validation sessions")
    return 0

if __name__ == "__main__": raise SystemExit(main())
