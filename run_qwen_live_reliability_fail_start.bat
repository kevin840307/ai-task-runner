@echo off
setlocal
pushd "%~dp0"

rem Fast re-run entry point after a live reliability failure.
rem Reuse the canonical 0.5H gate so smoke-matrix coverage cannot drift.
rem Default: resume from the currently reproduced failed probe (34 = api-disconnect).
rem Override example:
rem   run_qwen_live_reliability_fail_start.bat --start-probe 35
call "tool\qwen_live_reliability_0_5h.bat" --start-probe 34 %*

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
