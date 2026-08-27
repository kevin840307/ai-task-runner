@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "05_ai_quality_repair" -- %*
exit /b %ERRORLEVEL%
