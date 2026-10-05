@echo off
setlocal
if exist "%~dp0Runtime\Python\python.exe" (
  "%~dp0Runtime\Python\python.exe" "%~dp0Archon\Gate\CLI\archon.py" %*
) else (
  python "%~dp0Archon\Gate\CLI\archon.py" %*
)
exit /b %errorlevel%
