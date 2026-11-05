@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0\..\.."

echo ============================================================
echo AI Task Runner - REAL Qwen Concurrent Worktree Conflict Test
echo ============================================================
echo.
echo This test uses the existing Ralphy workflow:
echo   runner\assets\workflows\ralphy_ai_validate.yaml
echo.
echo Production path:
echo   Task A --^> real qwen.cmd Runner --^> isolated worktree
echo   Task B --^> real qwen.cmd Runner --^> isolated worktree
echo             both start from the same Main HEAD
echo                       ^|
echo                  Task A merges
echo                       ^|
echo                  Task B conflicts
echo                       ^|
echo            TaskRunService auto recovery
echo                       ^|
echo              recovery worktree + Qwen
echo                       ^|
echo                  merge to Main
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [FAIL] git.exe was not found in PATH.
  exit /b 2
)

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [FAIL] Python was not found in PATH.
    exit /b 2
  )
  set "PYTHON=python"
)

if "%QWEN_COMMAND%"=="" set "QWEN_COMMAND=qwen.cmd"

where "%QWEN_COMMAND%" >nul 2>nul
if errorlevel 1 (
  echo [FAIL] %QWEN_COMMAND% was not found in PATH.
  echo.
  echo If your Qwen CLI command is different, run:
  echo   set QWEN_COMMAND=your-qwen-command
  echo   %~nx0
  exit /b 2
)

echo [PRECHECK] Qwen CLI:
call "%QWEN_COMMAND%" --version
if errorlevel 1 (
  echo [FAIL] Qwen CLI exists but --version failed.
  exit /b 2
)

set "DEMO_ROOT=%TEMP%\ai-task-runner-live-qwen-worktree-conflict"
if exist "%DEMO_ROOT%" rmdir /s /q "%DEMO_ROOT%"

echo.
echo [RUN] Demo root: %DEMO_ROOT%
echo [RUN] Qwen command: %QWEN_COMMAND%
echo [RUN] Two initial Qwen Runners will execute concurrently.
echo [RUN] Ralphy AI validation is enabled for each Runner.
echo.
echo NOTE: This is a REAL Qwen test and consumes model/API usage.
echo.

%PYTHON% "examples\13_concurrent_worktree_conflict\live_qwen_demo.py" ^
  --root "%DEMO_ROOT%" ^
  --qwen-command "%QWEN_COMMAND%" ^
  --timeout 300

set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo [FAIL] Real Qwen concurrent conflict recovery test failed.
  echo.
  echo Inspect:
  echo   %DEMO_ROOT%\logs
  echo   %DEMO_ROOT%\project
  echo.
  echo Useful logs:
  echo   %DEMO_ROOT%\logs\task-a.log
  echo   %DEMO_ROOT%\logs\task-b.log
  echo   %DEMO_ROOT%\logs\recovery-1.log
  exit /b %RC%
)

echo ============================================================
echo [PASS] REAL Qwen worktree conflict recovery succeeded.
echo ============================================================
echo Final project:
echo   %DEMO_ROOT%\project
echo.
echo Logs:
echo   %DEMO_ROOT%\logs
echo.
echo Expected final shared.txt:
echo   enabled_tasks=BASE,TASK_A,TASK_B
echo.
exit /b 0
