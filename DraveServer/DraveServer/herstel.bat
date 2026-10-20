@echo off
setlocal
cd /d "%~dp0"
echo Dit verwijdert de .venv-map en bouwt de omgeving opnieuw op.
echo.
choice /M "Doorgaan"
if errorlevel 2 goto :einde

if exist ".venv" (
    echo Oude omgeving verwijderen...
    rmdir /s /q ".venv"
)

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
    echo Geen geschikte Python gevonden.
    pause
    exit /b 1
)

%PYEXE% -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install --only-binary=:all: -r requirements.txt
echo.
echo Klaar. Start de app met run.bat.
pause
:einde
endlocal
