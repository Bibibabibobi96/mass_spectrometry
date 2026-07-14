@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
"%SIMION%" --nogui --noprompt gem2pa oatof_detector_ground.gem detector_ground.pa#
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui --noprompt --quiet refine --resume=0 --convergence=5e-7 detector_ground.pa#
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui --noprompt fastadj detector_ground.pa0 "1=0"
exit /b %errorlevel%
