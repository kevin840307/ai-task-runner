@echo off
setlocal
pushd "%~dp0"
python ..\..\ai_task_runner.py --project-root . --goal-file prompt.md --validator validator.py --protect-file audit_plan.py --protect-file CASE_README.md --protect-file run_plan_only.cmd --protect-file run_full.cmd --protect-file reset_case.cmd --plan-only
set RUNNER_EXIT=%ERRORLEVEL%
python audit_plan.py
set AUDIT_EXIT=%ERRORLEVEL%
popd
if not "%RUNNER_EXIT%"=="0" exit /b %RUNNER_EXIT%
exit /b %AUDIT_EXIT%
