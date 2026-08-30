@echo off
setlocal
cd /d "%~dp0.."

echo === Builtin mixed workflow ===
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --scenario dryrunexample\builtin_mixed_scenario.yaml
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Existing custom workflow ===
python tool\workflow_dryrun.py examples\workflow_multi_prompt.yaml
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Dry-run stress workflow ===
python tool\workflow_dryrun.py dryrunexample\workflow.yaml --scenario dryrunexample\custom_scenario.yaml
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Builtin auto failure matrix ===
python tool\workflow_dryrun.py runner\workflow\builtin\mixed.yaml --matrix
if errorlevel 1 exit /b %errorlevel%

echo.
echo === Custom auto failure matrix ===
python tool\workflow_dryrun.py dryrunexample\workflow.yaml --matrix
if errorlevel 1 exit /b %errorlevel%

echo.
echo DRYRUN EXAMPLES PASSED
exit /b 0
