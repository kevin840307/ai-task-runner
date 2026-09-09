@echo off
setlocal
python "%~dp0..\tool\example_temp_runner.py" --all -- %*
exit /b %ERRORLEVEL%
