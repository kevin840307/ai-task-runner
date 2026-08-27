@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "11_regression_workflow_demo" -- --backend qwen --command "python ..\mock_agent.py" --force-new --retry-delay 0 --retry-wait 0 --retry-max-wait 0 %*
exit /b %ERRORLEVEL%
