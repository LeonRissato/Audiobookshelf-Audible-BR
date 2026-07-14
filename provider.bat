@echo off
chcp 65001 >nul
cd /d "%~dp0"
venv\Scripts\python provider_server.py
pause
