@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
cd /d "%~dp0"
"%SIMION%" --nogui gem2pa oatof_flight_tube_ground.gem oatof_flight_tube_ground.pa#
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui --quiet refine --resume=0 --convergence=5e-7 oatof_flight_tube_ground.pa#
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui fastadj oatof_flight_tube_ground.pa0 "1=0"
