@echo off
setlocal enabledelayedexpansion
title TechHoy — Instalador automatico

echo.
echo  ========================================
echo   TechHoy ^| Instalador automatico
echo  ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no encontrado.
    echo Descargalo desde: https://www.python.org/downloads/
    echo Asegurate de marcar "Add Python to PATH" al instalar.
    pause
    exit /b 1
)
echo [OK] Python encontrado.

:: Check Git
git --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Git no encontrado.
    echo Descargalo desde: https://git-scm.com/download/win
    pause
    exit /b 1
)
echo [OK] Git encontrado.

:: Create virtualenv
echo.
echo [1/4] Creando entorno virtual...
if not exist "venv" (
    python -m venv venv
    echo [OK] Entorno virtual creado.
) else (
    echo [OK] Entorno virtual ya existe.
)

:: Activate and install
echo.
echo [2/4] Instalando dependencias (puede tardar 3-5 minutos)...
call venv\Scripts\activate.bat
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.

:: Create .env if not exists
echo.
echo [3/4] Configurando fichero .env...
if not exist ".env" (
    copy .env.example .env >nul
    echo [OK] Fichero .env creado. DEBES rellenarlo con tus API keys.
) else (
    echo [OK] .env ya existe.
)

:: Create config directories
echo.
echo [4/4] Creando directorios necesarios...
if not exist "output" mkdir output
if not exist "logs" mkdir logs
if not exist "config" mkdir config
echo [OK] Directorios creados.

echo.
echo  ========================================
echo   Instalacion completada con exito!
echo  ========================================
echo.
echo  PROXIMOS PASOS:
echo.
echo  1. Edita el fichero .env con tus API keys:
echo     - DEEPSEEK_API_KEY
echo     - YOUTUBE_API_KEY
echo     - PEXELS_API_KEY
echo     - GOOGLE_APPLICATION_CREDENTIALS (opcional, para TTS gratis)
echo     - TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID (opcional)
echo.
echo  2. Pon tu google_credentials.json en la carpeta config\
echo.
echo  3. Autoriza YouTube (una sola vez):
echo     venv\Scripts\activate
echo     python setup_youtube_auth.py --channel techhoy
echo.
echo  4. Prueba el pipeline:
echo     python run_once.py
echo.
echo  5. Arranca el scheduler (publica automaticamente):
echo     python scheduler.py
echo.
pause
