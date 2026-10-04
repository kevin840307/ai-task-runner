@echo off
setlocal
pushd "%~dp0"

rem Fast re-run entry point after a live reliability failure.
rem Default: resume from the currently reproduced failed probe (30 = api-502).
rem Override example:
rem   run_qwen_live_reliability_fail_start.bat --start-probe 34
python "tool\qwen_live_reliability.py" --hours 0.5 --high-density --require-transient --single-process-yaml-items 4 --start-probe 30 %*

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
