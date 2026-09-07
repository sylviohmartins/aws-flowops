@echo off
setlocal
python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if errorlevel 1 goto use_launcher
python "%~dp0scripts\setup.py" %*
exit /b %errorlevel%

:use_launcher
py -3 "%~dp0scripts\setup.py" %*
exit /b %errorlevel%
