@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%
"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" -S apps\ddrum4-modernizer -B apps\ddrum4-modernizer\build-core -G Ninja -DDDRUM4_BUILD_APP=OFF
if errorlevel 1 exit /b %errorlevel%
"C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build apps\ddrum4-modernizer\build-core --target ddrum4_core_tests
if errorlevel 1 exit /b %errorlevel%
pushd apps\ddrum4-modernizer\build-core
ddrum4_core_tests.exe
set result=%errorlevel%
popd
exit /b %result%
