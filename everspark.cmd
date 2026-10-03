@echo off
setlocal
python "%~dp0Archon\Gate\CLI\archon.py" %*
exit /b %errorlevel%
