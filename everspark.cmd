@echo off
setlocal
if /I "%~1"=="archon" goto archon
echo Windows launcher currently supports: everspark archon start 1>&2
exit /b 2
:archon
python "%~dp0Archon\Gate\CLI\archon.py" "%~2"
exit /b %errorlevel%
