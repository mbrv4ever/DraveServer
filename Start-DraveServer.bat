@echo off
rem === Start-DraveServer.bat - lokale AI-chatserver ===
cd /d "%~dp0"

set "PY="
for %%V in (3.11 3.12 3.10 3.13) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY ( py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" )
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY ( echo Geen Python gevonden. Installeer Python 3.11 of 3.12. & pause & exit /b 1 )

%PY% -c "import gpt4all" >nul 2>&1
if errorlevel 1 (
  echo AI-engine installeren ^(gpt4all, eenmalig^)...
  %PY% -m pip install --upgrade pip
  %PY% -m pip install gpt4all
)

%PY% -c "import neuvoice" >nul 2>&1
if errorlevel 1 (
  echo Stem installeren ^(neuvoice, eenmalig - alleen nodig voor de stem^)...
  %PY% -m pip install --only-binary=:all: onnxruntime neuvoice
)

echo.
echo Server starten... (dit venster open laten; sluiten = server stopt)
echo.
%PY% "%~dp0server.py"
pause
