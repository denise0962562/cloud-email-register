@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Missing Windows virtualenv. Run: py -3 -m venv .venv
    echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)
".venv\Scripts\python.exe" "%~dp0windows_service.py" restart %*
exit /b %errorlevel%
