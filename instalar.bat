@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Criando ambiente virtual...
py -3 -m venv venv 2>nul || python -m venv venv
if errorlevel 1 (
    echo ERRO: Python nao encontrado. Instale em https://www.python.org/downloads/
    pause & exit /b 1
)
echo Instalando dependencias...
venv\Scripts\python -m pip install --quiet --upgrade pip
venv\Scripts\pip install --quiet -r requirements.txt
if not exist config.json copy config.json.example config.json >nul
echo.
echo Pronto! Agora edite o arquivo config.json com a URL e o token do seu Audiobookshelf.
pause
