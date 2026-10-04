@echo off
setlocal
pushd "%~dp0"

python "tool\qwen_live_reliability.py" --hours 0.5 --high-density --require-transient --single-process-yaml-items 4 --start-probe api-disconnect %*

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
