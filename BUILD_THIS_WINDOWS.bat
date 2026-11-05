@echo off
setlocal EnableExtensions
rem pushd maps a UNC share to a temporary drive letter for this session.
pushd "%~dp0"
if errorlevel 1 (
  echo Could not open the project folder. Copy it to a local Windows folder and try again.
  pause
  exit /b 1
)
echo NE-501 v1.0.1: build a portable program for this Windows computer.
echo Requirements: Windows 10/11 64-bit, Python 3.12 for the matching architecture, and internet.
echo This builds an EXE folder; it does not create the two-architecture installer.
echo.
set "DETECTED_ARCH=%PROCESSOR_ARCHITECTURE%"
if defined PROCESSOR_ARCHITEW6432 set "DETECTED_ARCH=%PROCESSOR_ARCHITEW6432%"
if /I "%DETECTED_ARCH%"=="ARM64" (set "BUILD_ARCH=arm64") else if /I "%DETECTED_ARCH%"=="AMD64" (set "BUILD_ARCH=x64") else (
  echo Unsupported Windows architecture: %DETECTED_ARCH%
  popd
  pause
  exit /b 1
)
echo Windows architecture: %BUILD_ARCH%
echo Python 3.12 for this architecture will be located automatically.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\build\build_arch.ps1" -Arch "%BUILD_ARCH%"
if errorlevel 1 (
  echo.
  echo Build did not complete. See the error above and README_Build.txt.
  popd
  pause
  exit /b 1
)
echo.
echo The complete portable application folder is in builds\%BUILD_ARCH%\NE501_Multi_Pump_Controller\
echo Keep the EXE and _internal folder together.
popd
pause
