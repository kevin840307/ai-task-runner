@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "09_config_environment_auditor" -- %*
exit /b %ERRORLEVEL%
