@echo off
rem === Start-DraveServer-Tray.bat - server in het systeemvak (geen zwart venster) ===
cd /d "%~dp0"

set "PY="
for %%V in (3.11 3.12 3.10 3.13) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY ( py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" )
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY ( echo Geen Python gevonden. Installeer Python 3.11 of 3.12. & pause & exit /b 1 )

%PY% -c "import gpt4all" >nul 2>&1 || ( echo AI-engine installeren... & %PY% -m pip install gpt4all )
%PY% -c "import pystray" >nul 2>&1 || ( echo Systeemvak-icoon installeren... & %PY% -m pip install pystray pillow )
%PY% -c "import neuvoice" >nul 2>&1 || ( echo Stem installeren... & %PY% -m pip install --only-binary=:all: onnxruntime neuvoice )
%PY% -c "import huggingface_hub" >nul 2>&1 || ( echo Model-downloader installeren... & %PY% -m pip install huggingface_hub )

rem pythonw = geen console; er verschijnt alleen het draken-icoon bij de klok
start "" pythonw "%~dp0tray.py" 2>nul || start "" %PY% "%~dp0tray.py"
