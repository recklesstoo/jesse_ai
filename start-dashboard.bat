@echo off
setlocal EnableDelayedExpansion
title Trading Dashboard Startup
color 0A

echo.
echo ========================================
echo    TRADING DASHBOARD STARTUP
echo ========================================
echo.

echo [*] Verificando y liberando puertos...
node scripts/port-manager.js cleanup >nul 2>&1
powershell -NoProfile -Command "Start-Sleep -Seconds 3"

echo [OK] Puertos verificados y liberados
echo.

echo [*] Iniciando Backend (Puerto 8000)...
start "Trading Backend" /min cmd /c "cd /d backend && python app.py"
powershell -NoProfile -Command "Start-Sleep -Seconds 5"

echo [*] Iniciando Frontend (Puerto 3001)...
start "Trading Frontend" /min cmd /c "cd /d frontend && npm run dev"
powershell -NoProfile -Command "Start-Sleep -Seconds 4"

echo.
echo [*] Verificando estado final de puertos...
if not exist logs mkdir logs
node scripts/port-manager.js check > logs\port-check.log 2>&1

echo.
echo ========================================
echo    [OK] DASHBOARD INICIADO EXITOSAMENTE
echo ========================================
echo.
echo Dashboard URL: http://localhost:3001
echo API URL:      http://localhost:8000
echo WebSocket:    ws://localhost:8000/ws/live
echo.
echo Tip: Si tienes problemas despues de reiniciar el sistema,
echo      ejecuta: node scripts/port-manager.js register-startup
echo      para configurar limpieza automatica de puertos.
echo.

start http://localhost:3001

endlocal
exit /b 0
