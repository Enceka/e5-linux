@echo off
rem Install OpenWrt onto an internal eMMC partition, no SD card needed.
call "%~dp0flash.cmd" --part %*
