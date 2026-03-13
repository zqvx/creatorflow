@echo off
title TikTok Scheduler - Setup
color 0B

echo.
echo  ==========================================
echo   SETUP - TikTok Scheduler
echo  ==========================================
echo.

cd /d "%~dp0"

:: ── Python check ──────────────────────────────────────────────────────────────
echo  [1/4] A verificar Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERRO] Python nao encontrado!
    echo.
    echo  Instala Python 3.10+ em:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANTE: marca "Add Python to PATH" durante a instalacao!
    echo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo  Python OK!
echo.

:: ── pip check ─────────────────────────────────────────────────────────────────
echo  [2/4] A atualizar pip...
python -m pip install --upgrade pip -q
echo  pip OK!
echo.

:: ── Install requirements ──────────────────────────────────────────────────────
echo  [3/4] A instalar dependencias...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo  [ERRO] Falha na instalacao das dependencias
    echo  Tenta correr como Administrador
    pause
    exit /b 1
)
echo.
echo  Dependencias instaladas!
echo.

:: ── Create structure ──────────────────────────────────────────────────────────
echo  [4/4] A criar estrutura de pastas...
if not exist "videos\" mkdir videos
if not exist "queue.json" echo [] > queue.json
echo  Estrutura criada!
echo.

:: ── Done ──────────────────────────────────────────────────────────────────────
echo  ==========================================
echo   SETUP COMPLETO!
echo  ==========================================
echo.
echo  Agora podes usar: metricool_free.bat
echo.
pause
