@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "03_ai_validator_voting" -- %*
exit /b %ERRORLEVEL%
