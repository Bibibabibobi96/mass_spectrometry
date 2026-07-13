@echo off
setlocal
set "SIMION=C:\Program Files\SIMION-2020\simion.exe"
set "ROOT=%~dp0"

"%SIMION%" --nogui gem2pa "%ROOT%oatof_reflectron_ideal_10_5.gem" "%ROOT%oatof_reflectron_ideal_10_5.pa#"
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui --quiet refine --resume=0 --convergence=5e-7 "%ROOT%oatof_reflectron_ideal_10_5.pa#"
if errorlevel 1 exit /b %errorlevel%
"%SIMION%" --nogui fastadj "%ROOT%oatof_reflectron_ideal_10_5.pa0" "1=0,2=145.454545,3=290.909091,4=436.363636,5=581.818182,6=727.272727,7=872.727273,8=1018.181818,9=1163.636364,10=1309.090909,11=1454.545455,12=1600,13=1733.333333,14=1866.666667,15=2000,16=2133.333333,17=2266.666667,18=2400,19=0"
