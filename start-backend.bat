@echo off
setlocal

REM =============================================================================
REM start-backend.bat
REM Arranque canónico del backend FastAPI (CMD)
REM =============================================================================

cd /d "%~dp0"

echo [INFO] Root: %cd%

REM --- Verificar venv ---
IF NOT EXIST ".venv\Scripts\activate.bat" (
  echo [ERROR] No existe .venv\Scripts\activate.bat
  exit /b 10
)

REM --- Verificar backend/app.py ---
IF NOT EXIST "backend\app.py" (
  echo [ERROR] No existe backend\app.py
  exit /b 11
)

REM --- Activar venv ---
echo [INFO] Activando venv...
call ".\.venv\Scripts\activate.bat"
IF ERRORLEVEL 1 (
  echo [ERROR] Fallo activando el venv
  exit /b 12
)

REM --- Verificar uvicorn ---
python -c "import uvicorn" >nul 2>&1
IF ERRORLEVEL 1 (
  echo [ERROR] uvicorn no esta instalado en el venv. Ejecuta: pip install uvicorn fastapi
  exit /b 13
)

REM --- Verificar puerto 8000 libre (no matar PID fijo) ---
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr LISTENING') do (
  echo [ERROR] Puerto 8000 ocupado. PID: %%a
  echo         Verifica proceso: tasklist /FI "PID eq %%a"
  echo         Para detener:     taskkill /F /PID %%a
  exit /b 20
)

echo [INFO] Iniciando backend en http://localhost:8000
echo [INFO] Ctrl+C para detener

python -m uvicorn app:app --app-dir backend --host 0.0.0.0 --port 8000 --reload

endlocal