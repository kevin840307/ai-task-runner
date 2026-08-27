@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "11_regression_workflow_demo" -- --backend qwen %*
exit /b %ERRORLEVEL%
