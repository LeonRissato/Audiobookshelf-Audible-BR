@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Sem argumentos = simulacao. Exemplos:
rem   sincronizar.bat --aplicar
rem   sincronizar.bat --aplicar --capas
rem   sincronizar.bat --aplicar --sobrescrever --biblioteca "Audiobooks"
venv\Scripts\python sync_library.py %*
pause
