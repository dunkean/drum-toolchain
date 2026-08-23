@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /EHsc /I firmware\ddrum4-midi-bridge\include /I firmware\ddrum4-midi-bridge\test\support firmware\ddrum4-midi-bridge\src\DdrumBridge.cpp firmware\ddrum4-midi-bridge\src\MidiDinAdapter.cpp firmware\ddrum4-midi-bridge\native_tests\bridge_core_msvc.cpp /Fo:build\firmware-core\ /Fe:build\firmware-core\bridge_core_tests.exe
if errorlevel 1 exit /b %errorlevel%
build\firmware-core\bridge_core_tests.exe
exit /b %errorlevel%
