@echo off
rem 荣悦 E5 OpenWrt 一键刷入 (Windows): the flasher is flash.py.
chcp 65001 >nul
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo 需要 Python 3 / Python 3 is needed: https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% flash.py %*
pause
