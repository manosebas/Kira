@echo off
rem ======================================================
rem KIRA - parar el cerebro y el puente
rem
rem Hace falta sobre todo para SUBIR FIRMWARE: el puente
rem tiene COM5 tomado en exclusiva y el upload falla
rem mientras este vivo.
rem
rem Tambien para libera el puerto 2000 si quieres usar
rem `eve dev` en lugar de produccion.
rem ======================================================

echo Parando el puente (pythonw)...
taskkill /F /IM pythonw.exe >nul 2>&1
if errorlevel 1 (echo   no estaba corriendo) else (echo   detenido)

echo Parando el cerebro (lo que escuche en el puerto 2000)...

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":2000" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%p >nul 2>&1
  echo   PID %%p detenido
)

echo.
echo Listo. COM5 y el puerto 2000 estan libres.
echo Para volver a arrancar: run_brain.cmd y luego run_bridge.cmd
