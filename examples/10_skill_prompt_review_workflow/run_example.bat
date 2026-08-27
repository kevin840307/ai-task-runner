@echo off
setlocal
python "%~dp0..\..\tool\example_temp_runner.py" --example "10_skill_prompt_review_workflow" -- %*
exit /b %ERRORLEVEL%
