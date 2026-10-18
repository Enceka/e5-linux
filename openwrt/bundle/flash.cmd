@echo off
rem Shared launcher; preserve the installer's exit code across pause.
chcp 65001 >nul
cd /d "%~dp0"
if exist "OpenWrt-Installer.exe" goto packaged_exe
if exist "flash.exe" goto legacy_exe
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto no_python
set "SCRIPT=flash.py"
if exist "OpenWrt-Installer.py" set "SCRIPT=OpenWrt-Installer.py"
%PY% "%SCRIPT%" %*
set "INSTALL_EXIT=%ERRORLEVEL%"
pause
exit /b %INSTALL_EXIT%
:packaged_exe
"%~dp0OpenWrt-Installer.exe" %*
set "INSTALL_EXIT=%ERRORLEVEL%"
pause
exit /b %INSTALL_EXIT%
:legacy_exe
"%~dp0flash.exe" %*
set "INSTALL_EXIT=%ERRORLEVEL%"
pause
exit /b %INSTALL_EXIT%
:no_python
echo No bundled installer executable and no Python 3. Install Python: https://www.python.org/downloads/
pause
exit /b 1
