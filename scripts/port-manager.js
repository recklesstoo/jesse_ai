#!/usr/bin/env node

/**
 * Port Manager - Gestiona puertos para evitar conflictos
 * Uso: node scripts/port-manager.js [check|kill|start|cleanup|register-startup]
 */

const { exec, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const PORTS = {
  backend: 8000,
  frontend: 3001
};

const PORT_FILE = path.join(__dirname, '..', '.ports.json');
const STARTUP_SCRIPT = path.join(__dirname, '..', 'startup-cleanup.bat');

function savePortInfo(ports) {
  fs.writeFileSync(PORT_FILE, JSON.stringify(ports, null, 2));
}

function loadPortInfo() {
  try {
    return JSON.parse(fs.readFileSync(PORT_FILE, 'utf8'));
  } catch {
    return {};
  }
}

function checkPort(port) {
  return new Promise((resolve) => {
    exec(`netstat -ano | findstr :${port}`, (error, stdout) => {
      if (error || !stdout.trim()) {
        resolve({ port, status: 'free', pid: null });
      } else {
        const lines = stdout.trim().split('\n');
        const pids = lines
          .map(line => {
            const parts = line.trim().split(/\s+/);
            return parts[parts.length - 1];
          })
          .filter(pid => pid && pid !== '0');

        resolve({
          port,
          status: 'occupied',
          pid: pids[0] || 'unknown',
          processes: pids.length
        });
      }
    });
  });
}

function killPort(port) {
  return new Promise((resolve) => {
    // Mejorado: usar multiples metodos para liberar puertos
    const commands = [
      `for /f "tokens=5" %a in ('netstat -aon ^| findstr :${port}') do taskkill /f /pid %a`,
      `netsh interface portproxy delete v4tov4 listenport=${port}`,
      `netsh advfirewall firewall delete rule name="Block_Port_${port}"`
    ];

    let completed = 0;
    let success = false;

    commands.forEach(cmd => {
      exec(cmd, (error) => {
        if (!error) success = true;
        completed++;
        if (completed === commands.length) {
          resolve(success);
        }
      });
    });

    // Timeout despues de 5 segundos
    setTimeout(() => {
      if (completed < commands.length) {
        resolve(success);
      }
    }, 5000);
  });
}

function forceKillProcessByName(processName) {
  return new Promise((resolve) => {
    exec(`taskkill /f /im ${processName}`, (error) => {
      resolve(!error);
    });
  });
}

async function aggressivePortCleanup() {
  console.log('Limpieza agresiva de puertos...\n');

  // Matar procesos comunes que pueden ocupar los puertos
  const processesToKill = ['node.exe', 'python.exe', 'uvicorn.exe', 'npm.exe'];

  for (const process of processesToKill) {
    console.log(`Terminando procesos ${process}...`);
    await forceKillProcessByName(process);
  }

  // Liberar puertos especificos
  for (const [service, port] of Object.entries(PORTS)) {
    console.log(`Liberando puerto ${port} (${service}) agresivamente...`);
    await killPort(port);

    // Verificar si se libero
    const result = await checkPort(port);
    if (result.status === 'free') {
      console.log(`OK: Puerto ${port} liberado exitosamente`);
    } else {
      console.log(`WARN: Puerto ${port} aun ocupado (PID: ${result.pid})`);
    }
  }

  console.log('\nOK: Limpieza agresiva completada');
}

function createStartupScript() {
  const scriptContent = `@echo off
REM Startup cleanup script for Trading Dashboard
REM This script runs on system startup to clean ports

echo [%date% %time%] Trading Dashboard - Startup Cleanup >> "%~dp0startup.log"

REM Kill common processes that might hold ports
taskkill /f /im node.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im uvicorn.exe >nul 2>&1

REM Clean specific ports
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3001') do taskkill /f /pid %%a >nul 2>&1

REM Clean port proxy rules
netsh interface portproxy delete v4tov4 listenport=8000 >nul 2>&1
netsh interface portproxy delete v4tov4 listenport=3001 >nul 2>&1

echo [%date% %time%] Startup cleanup completed >> "%~dp0startup.log"
`;

  fs.writeFileSync(STARTUP_SCRIPT, scriptContent);
  console.log(`OK: Script de startup creado: ${STARTUP_SCRIPT}`);
}

function registerStartupCleanup() {
  return new Promise((resolve) => {
    // Crear el script de startup
    createStartupScript();

    // Registrar en el registro de Windows para ejecutar al inicio
    const regCommand = `reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "TradingDashboardCleanup" /t REG_SZ /d "${STARTUP_SCRIPT}" /f`;

    exec(regCommand, (error, stdout, stderr) => {
      if (error) {
        console.log('ERROR: Error registrando startup cleanup:', error.message);
        console.log('TIP: Ejecuta como administrador para registrar automaticamente');
        console.log(`TIP: O ejecuta manualmente: ${STARTUP_SCRIPT}`);
        resolve(false);
      } else {
        console.log('OK: Startup cleanup registrado exitosamente');
        console.log('INFO: Se ejecutara automaticamente en cada reinicio del sistema');
        resolve(true);
      }
    });
  });
}

async function checkAllPorts() {
  console.log('Verificando puertos...\n');

  let allFree = true;
  const portInfo = {};

  for (const [service, port] of Object.entries(PORTS)) {
    const result = await checkPort(port);
    const status = result.status === 'free' ? 'OK: Libre' : `Ocupado (PID: ${result.pid})`;
    console.log(`${service.padEnd(10)} Puerto ${port}: ${status}`);

    portInfo[service] = result;
    if (result.status !== 'free') {
      allFree = false;
    }
  }

  if (!allFree) {
    console.log('\nWARN: Algunos puertos estan ocupados. Usa "kill" para liberarlos.');
  }

  console.log('\nGuardando informacion de puertos...');
  savePortInfo({
    timestamp: new Date().toISOString(),
    ports: PORTS,
    portInfo: portInfo,
    lastCheck: Date.now(),
    allFree: allFree
  });

  return allFree;
}

async function killAllPorts() {
  console.log('Liberando puertos...\n');

  for (const [service, port] of Object.entries(PORTS)) {
    console.log(`Liberando puerto ${port} (${service})...`);
    const success = await killPort(port);
    console.log(success ? 'OK: Liberado' : 'WARN: No se pudo liberar completamente');
  }

  // Verificar que se liberaron
  console.log('\nVerificando liberacion...');
  const allFree = await checkAllPorts();

  if (!allFree) {
    console.log('\nWARN: Algunos puertos siguen ocupados. Intentando limpieza agresiva...');
    await aggressivePortCleanup();
  }

  console.log('\nOK: Proceso de liberacion completado');
}

async function startServices() {
  console.log('Iniciando servicios...\n');

  // Verificar que los puertos esten libres
  const allFree = await checkAllPorts();

  if (!allFree) {
    console.log('\nWARN: Algunos puertos estan ocupados. Liberando automaticamente...');
    await killAllPorts();
  }

  console.log('\nPara iniciar los servicios manualmente:');
  console.log('Backend:  cd backend && python app.py');
  console.log('Frontend: cd frontend && npm run dev');
  console.log('\nURLs:');
  console.log(`Backend:  http://localhost:${PORTS.backend}`);
  console.log(`Frontend: http://localhost:${PORTS.frontend}`);
}

async function main() {
  const command = process.argv[2] || 'check';

  console.log('Port Manager - Trading Dashboard\n');

  switch (command) {
    case 'check':
      await checkAllPorts();
      break;
    case 'kill':
      await killAllPorts();
      break;
    case 'start':
      await startServices();
      break;
    case 'cleanup':
      await aggressivePortCleanup();
      break;
    case 'register-startup':
      await registerStartupCleanup();
      break;
    default:
      console.log('Uso: node scripts/port-manager.js [check|kill|start|cleanup|register-startup]');
      console.log('  check           - Verificar estado de puertos');
      console.log('  kill            - Liberar puertos ocupados');
      console.log('  start           - Verificar puertos e instrucciones de inicio');
      console.log('  cleanup         - Limpieza agresiva de puertos y procesos');
      console.log('  register-startup - Registrar limpieza automatica al inicio del sistema');
  }
}

if (require.main === module) {
  main().catch(console.error);
}

module.exports = { checkPort, killPort, PORTS, aggressivePortCleanup };