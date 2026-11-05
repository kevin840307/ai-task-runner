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
echo AI Task Runner - Concurrent Worktree Conflict Recovery Demo
echo ============================================================
echo.
echo This will:
echo   1. Create a temporary Git project.
echo   2. Prepare TWO isolated Task worktrees from the same base.
echo   3. Start TWO real Runner processes at the same time.
echo   4. Merge Task A.
echo   5. Force Task B to conflict on shared.txt.
echo   6. Create a recovery worktree from the latest target.
echo   7. Run Runner again to repair the conflict.
echo   8. Merge the recovery result and verify the final Git tree.
echo.

%PYTHON% "examples\13_concurrent_worktree_conflict\demo.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [PASS] Concurrent Runner/worktree conflict recovery demo passed.
) else (
  echo [FAIL] Demo failed with exit code %RC%.
)
exit /b %RC%
