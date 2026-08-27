@echo off
rem ======================================================
rem KIRA - el puente (microfono, STT, TTS, parlante)
rem
rem Lo arranca la tarea programada "Kira Bridge" al iniciar
rem sesion. Tambien se puede ejecutar a mano para probar.
rem
rem Usa pythonw en vez de python para que NO aparezca ninguna
rem ventana de consola. Por eso la salida va a un log: sin
rem redirigirla no habria forma de ver que paso.
rem
rem El puente espera a que eve responda antes de seguir
rem (KIRA_EVE_WAIT segundos), asi que no importa cual de las
rem dos tareas arranque primero.
rem ======================================================

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

rem Sin telemetria de nivel: en produccion nadie lee la consola
rem y solo ensuciaria el log.
set KIRA_SHOW_LEVELS=0

rem Margen generoso: en un arranque en frio el disco esta ocupado
rem y eve puede tardar.
set KIRA_EVE_WAIT=180

echo [%date% %time%] arrancando kira_bridge.py >> "logs\bridge.log"

rem -u obligatorio: al redirigir a un archivo Python bufferea stdout
rem por bloques, asi que sin esto el log se queda vacio hasta que el
rem proceso muere y no hay forma de ver si arranco bien.
pythonw -u kira_bridge.py >> "logs\bridge.log" 2>&1

echo [%date% %time%] kira_bridge.py termino con codigo %errorlevel% >> "logs\bridge.log"
