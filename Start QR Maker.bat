@echo off
setlocal
cd /d "%~dp0"
if not exist ".cache\tmp" mkdir ".cache\tmp"
set "TMP=%CD%\.cache\tmp"
set "TEMP=%CD%\.cache\tmp"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up QR Studio...
    python -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m ensurepip --upgrade
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -c "import qrcode, PIL" >nul 2>&1
if errorlevel 1 (
    echo Installing QR Studio dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" QR.PY
if errorlevel 1 goto :error
exit /b 0
:error
echo.
echo QR Studio could not start. Check the error above.
echo Install Python 3.10 or newer and try again.
pause
exit /b 1
