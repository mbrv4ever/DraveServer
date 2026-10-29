@echo off
rem === Build-DraveServer-EXE.bat - bouwt DraveServer.exe (systeemvak-app) ===
cd /d "%~dp0"

set "PY="
for %%V in (3.11 3.12 3.10 3.13) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V" )
)
if not defined PY ( py -3 -c "import sys" >nul 2>&1 && set "PY=py -3" )
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY ( echo Geen Python gevonden. & pause & exit /b 1 )

echo Benodigdheden controleren/installeren...
%PY% -c "import gpt4all" 2>nul || %PY% -m pip install gpt4all
%PY% -c "import pystray" 2>nul || %PY% -m pip install pystray
%PY% -c "import PIL" 2>nul || %PY% -m pip install pillow
%PY% -c "import neuvoice" 2>nul || %PY% -m pip install --only-binary=:all: onnxruntime neuvoice
%PY% -c "import huggingface_hub" 2>nul || %PY% -m pip install huggingface_hub
%PY% -c "import PyInstaller" 2>nul || %PY% -m pip install pyinstaller

echo Icoon (her)bouwen...
%PY% make_icon.py

rem draaiende instantie afsluiten zodat de exe niet vergrendeld is
taskkill /f /im DraveServer.exe >nul 2>&1
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo EXE bouwen (kan enkele minuten duren)...
rem --onedir (GEEN --onefile): alles blijft in de eigen map dist\DraveServer\,
rem er wordt NIETS naar %%TEMP%%/AppData uitgepakt (portable) en de gpt4all-DLL
rem laadt betrouwbaar.
%PY% -m PyInstaller --noconfirm --clean --windowed --onedir ^
  --name DraveServer --icon assets\icon.ico ^
  --collect-all gpt4all ^
  --collect-binaries gpt4all ^
  --collect-all neuvoice ^
  --collect-all onnxruntime ^
  --collect-all huggingface_hub ^
  --hidden-import pystray._win32 ^
  --hidden-import tkinter ^
  --hidden-import drave_update ^
  tray.py

if not exist "dist\DraveServer\DraveServer.exe" (
  echo.
  echo BOUW MISLUKT - dist\DraveServer\DraveServer.exe niet gevonden. Lees de melding hierboven.
  pause
  exit /b 1
)

rem assets naast de exe zetten (de app leest assets uit de exe-map)
if not exist "dist\DraveServer\assets" mkdir "dist\DraveServer\assets"
copy /y "assets\icon.ico" "dist\DraveServer\assets\" >nul
copy /y "assets\logo.png" "dist\DraveServer\assets\" >nul

echo.
echo KLAAR. De app-map is:  dist\DraveServer\
echo Start 'm met:          dist\DraveServer\DraveServer.exe
echo (Verplaats de HELE map DraveServer, niet alleen de .exe.)
echo Alles blijft portable in die map - niets in Temp of AppData.
echo Een model in ..\DraveChat\cache\models of via het beheerscherm is nodig.
pause
