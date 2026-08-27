@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "02_repair_cycle" -- %*
exit /b %ERRORLEVEL%
