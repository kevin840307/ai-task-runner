@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --exec "examples/11_regression_workflow_demo/test_demo.py" -- %*
exit /b %ERRORLEVEL%
