@echo off
setlocal
pushd "%~dp0"

rem Fast re-run entry point after a live reliability failure.
rem Reuse the canonical 0.5H gate so smoke-matrix coverage cannot drift.
rem Default: resume at the final long-running gate (46 = soak).
rem Override example:
rem   run_qwen_live_reliability_fail_start.bat --start-probe 43
call "tool\qwen_live_reliability_0_5h.bat" --start-probe 46 %*

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
