@echo off
setlocal
pushd "%~dp0"
python "..\ai_task_runner.py" --project-root "." --script "examples.yaml" %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
