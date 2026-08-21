@echo off
setlocal
cd /d "%~dp0"
python "..\..\ai_task_runner.py" --project-root "." --script "example.yaml" %*
