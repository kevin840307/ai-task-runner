@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "02_validator_reroute_cycle" -- %*
exit /b %ERRORLEVEL%
