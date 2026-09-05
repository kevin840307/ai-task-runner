@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "01_basic_command_validator" -- %*
exit /b %ERRORLEVEL%
