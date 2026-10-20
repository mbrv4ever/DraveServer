@echo off
setlocal
cd /d "%~dp0"
echo === DraveServer - losse .exe bouwen ===

if not exist ".venv\Scripts\python.exe" (
    echo Voer eerst run.bat uit zodat de omgeving bestaat.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo PyInstaller installeren...
    python -m pip install --only-binary=:all: pyinstaller
)

if not exist "app.ico" (
    echo Pictogram maken...
    python maak_icoon.py
)

python -m PyInstaller --noconfirm app.spec
echo.
echo Klaar. De exe staat in de map dist\.
pause
endlocal
