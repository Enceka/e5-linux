@echo off
rem Rewrite an existing internal partition system: Android user data, the
rem userdata filesystem and the partition table all stay.
call "%~dp0flash.cmd" --reinstall-part %*
