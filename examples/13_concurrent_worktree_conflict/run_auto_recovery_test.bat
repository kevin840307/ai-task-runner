@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."

where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)

echo ============================================================
echo AI Task Runner - AUTO TaskRunService Conflict Recovery Test
echo ============================================================
echo.
echo Production path under test:
echo   TaskRunService.start A + B concurrently
echo     ^> two isolated Git worktrees
echo     ^> two real ai_task_runner.py subprocesses
echo     ^> Task A merges to Main
echo     ^> Task B hits a real app.txt merge conflict
echo     ^> TaskRunService automatically creates recovery worktree
echo     ^> automatically launches a third Runner for merge repair
echo     ^> recovery snapshot merges to Main
echo.
echo Running dedicated pytest...
echo.

%PYTHON% -m pytest -vv -s --tb=short "tests\test_runner_worktree_conflict_recovery_example.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [PASS] Automatic concurrent Runner/worktree conflict recovery passed.
) else (
  echo [FAIL] Automatic recovery test failed with exit code %RC%.
)
exit /b %RC%
