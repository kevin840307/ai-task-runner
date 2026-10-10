@echo off
setlocal
cd /d "%~dp0.."

echo === Built-in mixed workflow ===
python tool\workflow_dryrun.py runner\assets\workflows\mixed.yaml --scenario dryrunexample\system_mixed_scenario.yaml
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Custom result-edge workflow ===
python tool\workflow_dryrun.py dryrunexample\workflow.yaml --scenario dryrunexample\custom_scenario.yaml
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Built-in failure matrix ===
python tool\workflow_dryrun.py runner\assets\workflows\mixed.yaml --matrix
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Custom failure matrix ===
python tool\workflow_dryrun.py dryrunexample\workflow.yaml --matrix
if errorlevel 1 exit /b %errorlevel%

echo.
echo DRYRUN EXAMPLES PASSED
exit /b 0
