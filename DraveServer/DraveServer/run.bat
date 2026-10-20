@echo off
setlocal
cd /d "%~dp0"

set "PYEXE="
for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PYEXE (
        py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
    )
)
if not defined PYEXE (
    python -c "import sys" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo Geen geschikte Python 3.10-3.13 gevonden.
    echo Installeer Python via https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Eenmalige installatie van de omgeving...
    %PYEXE% -m venv .venv
)
call ".venv\Scripts\activate.bat"

python -c "import PyQt6, cryptography, acme, pymysql, qrcode, PyQt6.QtWebEngineWidgets" >nul 2>&1
if errorlevel 1 (
    echo PyQt6 installeren ^(eenmalig^)...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install --only-binary=:all: -r requirements.txt
)

python app.py
if errorlevel 1 (
    echo.
    echo Er ging iets mis. Bekijk app-fout.txt of start start-debug.bat.
    pause
)
endlocal
