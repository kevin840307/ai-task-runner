@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "06_yaml_driven_tool" -- %*
exit /b %ERRORLEVEL%
