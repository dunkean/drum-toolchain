@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%
"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" -S apps\ddrum4-modernizer -B apps\ddrum4-modernizer\build-core -G Ninja -DDDRUM4_BUILD_APP=OFF
if errorlevel 1 exit /b %errorlevel%
"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build apps\ddrum4-modernizer\build-core --target ddrum4_core_tests ddrum4_rig_runtime_tests
if errorlevel 1 exit /b %errorlevel%
pushd apps\ddrum4-modernizer\build-core
set result=0
ddrum4_core_tests.exe
if errorlevel 1 set result=%errorlevel%
ddrum4_rig_runtime_tests.exe
if errorlevel 1 set result=%errorlevel%
popd
exit /b %result%
