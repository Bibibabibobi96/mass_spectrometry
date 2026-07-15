@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
"%SIMION%" --nogui lua "%~dp0build_detector_variant.lua" ^
  "%~dp0oatof_detector_ground.gem" "%~dp0detector_ground.pa#" ^
  0.5 0.01 40 0.05 0.2 0.05 1 64
exit /b %errorlevel%
