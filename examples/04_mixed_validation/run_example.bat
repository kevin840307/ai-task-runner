@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "04_mixed_validation" -- %*
exit /b %ERRORLEVEL%
