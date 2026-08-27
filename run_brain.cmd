@echo off
rem ======================================================
rem KIRA - el cerebro (agente eve) en modo PRODUCCION
rem
rem Lo arranca la tarea programada "Kira Brain" al iniciar
rem sesion. Tambien se puede ejecutar a mano para probar.
rem
rem Lee brain\.env.local por su cuenta (OPENAI_API_KEY y
rem KIRA_AGENT_TOKEN), asi que no hay secretos aqui.
rem ======================================================

cd /d "%~dp0brain"

rem Mismo puerto que `eve dev`, a proposito: asi el puente no
rem necesita configuracion. Si intentas correr los dos a la vez,
rem el segundo falla con un error claro de puerto ocupado.
set PORT=2000

if not exist "%~dp0logs" mkdir "%~dp0logs"

if not exist ".output\server\index.mjs" (
  echo No hay build. Ejecutando eve build...
  call "node_modules\.bin\eve.cmd" build >> "%~dp0logs\brain.log" 2>&1
)

echo [%date% %time%] arrancando eve start en el puerto %PORT% >> "%~dp0logs\brain.log"

call "node_modules\.bin\eve.cmd" start >> "%~dp0logs\brain.log" 2>&1

echo [%date% %time%] eve start termino con codigo %errorlevel% >> "%~dp0logs\brain.log"
