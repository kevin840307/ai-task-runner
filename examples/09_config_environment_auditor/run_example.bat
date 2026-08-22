@echo off
setlocal
cd /d "%~dp0"
python "..\..\ai_task_runner.py" --loop-context-compress --project-root "." --script "example.yaml" %*
