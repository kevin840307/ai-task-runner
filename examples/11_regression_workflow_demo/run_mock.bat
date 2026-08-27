@echo off
setlocal
set "EX=%~dp0"
set "ROOT=%EX%project"
python "%EX%..\..\ai_task_runner.py" --goal-file "%EX%goal.md" --project-root "%ROOT%" --workflow "%EX%workflow.yaml" --validator ai --backend qwen --command "python ..\mock_agent.py" --force-new
endlocal
