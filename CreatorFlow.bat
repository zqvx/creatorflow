@echo off
title Overflow
color 0A
cd /d "%~dp0"
echo.
echo  ==========================================
echo   Overflow
echo  ==========================================
echo.
echo  [1] A verificar Python...
python --version
if %errorlevel% neq 0 (
    echo  [ERRO] Python nao encontrado!
    echo  Instala em https://www.python.org/downloads/ e marca "Add Python to PATH"
    pause & exit /b 1
)
echo.
echo  [2] A instalar dependencias...
python -m pip install streamlit requests pystray pillow yt-dlp -q
if %errorlevel% neq 0 (
    echo  [ERRO] Falha. Corre como Administrador.
    pause & exit /b 1
)
echo  OK!
echo.
echo  [3] A limpar porta 8501...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8501 " 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul
echo  OK!
echo.
echo  [4] A preparar ficheiros...
if not exist "videos\" mkdir videos
if not exist "queue.json" echo [] > queue.json
echo  OK!
echo.
echo  ==========================================
echo   A lancar icone na bandeja do Windows...
echo   Esta janela fecha em 3 segundos.
echo  ==========================================
echo.
echo  Procura o icone T na bandeja (canto inf. direito)
echo  Clica direito no icone para abrir a app
echo.
timeout /t 3 /nobreak >nul
start "" pythonw tray.py
timeout /t 2 /nobreak >nul
exit
