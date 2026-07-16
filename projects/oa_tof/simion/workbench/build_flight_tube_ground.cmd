@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
cd /d "%~dp0"
"%SIMION%" --nogui lua build_flight_tube_variant.lua "%~dp0oatof_flight_tube_ground.gem" "%~dp0oatof_flight_tube_ground.pa#" 1 1 0.1 350 10 10 -40 619.83
