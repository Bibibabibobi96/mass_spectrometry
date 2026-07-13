@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
set "HERE=%~dp0"
cd /d "%HERE%"
if not exist "oatof_ideal.iob" (
  echo ERROR: oatof_ideal.iob has not yet been created by SIMION Workbench.
  exit /b 2
)
"%SIMION%" --nogui fly --trajectory-quality 8 --particles oatof_single_100amu.ion oatof_ideal.iob
