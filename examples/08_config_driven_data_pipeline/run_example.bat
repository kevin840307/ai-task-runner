@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "08_config_driven_data_pipeline" -- %*
exit /b %ERRORLEVEL%
