@echo off
setlocal
pushd "%~dp0"
for %%D in (.ai-task-runner taskflow tests) do if exist "%%D" rmdir /s /q "%%D"
for %%F in (worklog.py) do if exist "%%F" del /q "%%F"
echo Case reset complete.
popd
