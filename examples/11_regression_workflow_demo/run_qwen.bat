@echo off
setlocal
set "EX=%~dp0"
set "ROOT=%EX%project"
python "%EX%..\..\ai_task_runner.py" --goal-file "%EX%goal.md" --project-root "%ROOT%" --workflow "%EX%workflow.yaml" --validator ai --backend qwen --final-ai-validations 5 --final-ai-required-passes 3 --force-new
endlocal
