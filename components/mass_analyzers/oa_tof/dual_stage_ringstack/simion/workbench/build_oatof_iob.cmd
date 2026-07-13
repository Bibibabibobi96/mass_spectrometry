@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
cd /d "%~dp0"
"%SIMION%" --nogui --noprompt lua build_oatof_iob.lua
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui --noprompt lua verify_oatof_iob.lua
