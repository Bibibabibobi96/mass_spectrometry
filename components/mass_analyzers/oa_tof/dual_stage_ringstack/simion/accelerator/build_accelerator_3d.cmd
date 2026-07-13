@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
set "HERE=%~dp0"
cd /d "%HERE%"
"%SIMION%" --nogui gem2pa oatof_accelerator_3d.gem oatof_accelerator_3d.pa#
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui --quiet refine --resume=0 --convergence=5e-7 oatof_accelerator_3d.pa#
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui fastadj oatof_accelerator_3d.pa0 1=2240,2=1760,3=1466.666667,4=1173.333333,5=880,6=586.666667,7=293.333333,8=0,9=0
