@echo off
setlocal
pushd "%~dp0"

if "%~1"=="" (
    python "tool\qwen_live_reliability.py" --hours 0.5 --high-density --require-transient
) else (
    python "tool\qwen_live_reliability.py" %*
)

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
