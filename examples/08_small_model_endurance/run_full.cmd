@echo off
setlocal
pushd "%~dp0"
if exist ".ai-task-runner\state.json" (
  python ..\..\ai_task_runner.py --project-root . --goal-file prompt.md --validator validator.py --protect-file audit_plan.py --protect-file CASE_README.md --protect-file run_plan_only.cmd --protect-file run_full.cmd --protect-file reset_case.cmd --resume
) else (
  python ..\..\ai_task_runner.py --project-root . --goal-file prompt.md --validator validator.py --protect-file audit_plan.py --protect-file CASE_README.md --protect-file run_plan_only.cmd --protect-file run_full.cmd --protect-file reset_case.cmd
)
set RUNNER_EXIT=%ERRORLEVEL%
echo.
echo ===== FINAL VALIDATOR =====
python validator.py --project-root .
set VALIDATOR_EXIT=%ERRORLEVEL%
echo.
echo ===== PLAN AUDIT =====
python audit_plan.py
set AUDIT_EXIT=%ERRORLEVEL%
popd
if not "%RUNNER_EXIT%"=="0" exit /b %RUNNER_EXIT%
if not "%VALIDATOR_EXIT%"=="0" exit /b %VALIDATOR_EXIT%
exit /b %AUDIT_EXIT%
