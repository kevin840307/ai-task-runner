@echo off
setlocal EnableExtensions

cd /d "%~dp0\..\.."

where python >nul 2>nul
if errorlevel 1 (
  echo [FAIL] python was not found in PATH.
  exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
  echo [FAIL] git was not found in PATH.
  exit /b 1
)

set "DEMO_OUT=%TEMP%\ai-task-runner-concurrent-conflict-demo"
echo ============================================================
echo AI Task Runner - Concurrent Worktree Conflict Recovery Demo
echo ============================================================
echo Output: %DEMO_OUT%
echo.

python "%~dp0run_demo.py" --output "%DEMO_OUT%"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo [FAIL] Concurrent Runner/worktree conflict recovery demo failed.
  echo Check logs under: %DEMO_OUT%\logs
  exit /b %RC%
)

echo [PASS] Both Tasks ran concurrently in isolated worktrees.
echo [PASS] Task B produced a real merge conflict after Task A merged.
echo [PASS] Recovery Runner resolved the conflict and merged successfully.
echo Demo repo: %DEMO_OUT%\project
echo Logs:      %DEMO_OUT%\logs
exit /b 0
