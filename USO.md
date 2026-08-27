# USO — Trabajar con Kira día a día

Qué hacer en cada caso. Para el estado del proyecto ver `ROADMAP.md`.

---

## Las dos piezas que tienes que arrancar

Kira son **dos programas**, y los dos corren en tu PC:

| Pieza | Qué es | Qué ocupa |
|---|---|---|
| **el cerebro** | el agente eve, decide y responde | puerto **2000** |
| **el puente** | micrófono, transcripción, voz, parlante | **COM5** |

Nada más. No hay nube, no hay servidor remoto. GitHub es solo respaldo.

## Y el cerebro tiene dos modos

| | `eve dev` — DESARROLLO | `eve start` — PRODUCCIÓN |
|---|---|---|
| Recarga al guardar un archivo | **sí** | no, hay que recompilar |
| Necesita el token | no | **sí** |
| Ventana / consola | sí, ves lo que pasa | no, silenciosa |
| Cuándo usarlo | mientras construyes | cuando solo quieres usarla |

Los dos usan el puerto 2000 a propósito, así que **nunca corras los dos a la vez**.

---

## Caso 1 — Configurar agentes (lo que vas a hacer ahora)

Editar `brain/agent/instructions.md`, crear subagentes, escribir tools.

**Usa modo desarrollo.** Dos terminales:

```powershell
# terminal 1 — el cerebro, con recarga automática
cd brain
npm exec -- eve dev --no-ui
```

```powershell
# terminal 2 — el puente, con consola para ver los niveles
python kira_bridge.py
```

**Y ya está: edita y habla. No reinicies nada.**

Verificado que la recarga en caliente funciona para:

- ✅ **cambiar texto** en `instructions.md` (raíz o subagente) → efecto en la frase siguiente
- ✅ **crear un subagente nuevo** (`agent/subagents/loquesea/`) → lo detecta en vivo,
  sin reiniciar

Lo único que **sí** pide reiniciar el cerebro:

- cambiar `agent/agent.ts` (el modelo)
- cambiar `agent/channels/eve.ts` (la autenticación)
- instalar un paquete nuevo con `npm install`
- editar `brain/.env.local`

### Iterar sin hardware — el atajo que ahorra tiempo

Si estás ajustando cómo responde un agente, **no necesitas hablarle**. Arranca el cerebro
con su REPL y escríbele:

```powershell
cd brain
npm exec -- eve dev
```

Sin `--no-ui` te abre una consola interactiva donde escribes y ves la respuesta al instante.
Nada de micrófono, nada de esperar 3 segundos de silencio, nada de que Whisper entienda mal.

Cuando la respuesta ya te guste, pasas a probarla por voz.

### Ver a qué subagente delegó

En la terminal del puente aparece:

```
Pensando...
  -> delegando en el subagente: correo
```

Si no aparece esa línea, **el raíz contestó él solo** sin delegar. Y si delega al equivocado,
el problema está en la `description` del subagente: es lo único que el raíz lee para decidir.

---

## Caso 2 — Cambiar el firmware (`src/main.cpp`)

**El puente tiene COM5 en exclusiva. Hay que soltarlo o el upload falla.**

```powershell
stop_kira.cmd                      # o Ctrl+C en la terminal del puente
platformio run --target upload
python kira_bridge.py              # volver a arrancar el puente
```

El cerebro puede quedarse corriendo: no toca el puerto serie.

Si esptool no conecta (`Failed to connect to ESP32`), durante el mensaje "Connecting...":
mantén **BOOT**, pulsa y suelta **EN**, sigue con BOOT, y suéltalo cuando lo reconozca.

Solo compilar, sin tocar la placa: `platformio run`.

---

## Caso 3 — Cambiar el puente (`kira_bridge.py`)

**Ctrl+C** en su terminal y arrancarlo otra vez. El cerebro no se toca.

Ojo: cada arranque **recarga Whisper**, y eso tarda. Es lo más lento del ciclo.

---

## Caso 4 — Solo usar Kira, sin desarrollar

```
run_brain.cmd
run_bridge.cmd
```

Doble clic o desde la terminal. **No abren ninguna ventana.**

Comprobar que arrancaron:

```powershell
type logs\bridge.log        # debe terminar en: Di: "Oye Kira..."
type logs\brain.log         # debe decir: server listening
```

Pararla: `stop_kira.cmd`

---

## Caso 5 — Mañana enciendo la computadora

**Nada arranca solo todavía.** El arranque automático está aplazado a propósito hasta
terminar el proyecto (ver `ROADMAP.md`), porque tomaría COM5 en cada inicio de sesión y
estorbaría cada vez que subas firmware.

Así que decide qué vas a hacer:

**¿Voy a tocar agentes o firmware?** → modo desarrollo (caso 1)

**¿Solo quiero usarla?** → `run_brain.cmd` + `run_bridge.cmd` (caso 4)

---

## Caso 6 — Verificar que algo funciona también en producción

Los agentes se comportan igual en los dos modos, pero producción no recarga: **hay que
recompilar**.

```powershell
stop_kira.cmd
cd brain
npm exec -- eve build
cd ..
run_brain.cmd
run_bridge.cmd
```

`run_brain.cmd` compila solo si no existe el build. Si ya existe pero cambiaste código,
**tienes que ejecutar `eve build` a mano**.

---

## Cuando algo no funciona

| Síntoma | Causa casi segura |
|---|---|
| El upload de firmware falla | el puente tiene COM5 → `stop_kira.cmd` |
| `eve` no arranca, puerto ocupado | ya hay un cerebro corriendo → `stop_kira.cmd` |
| El puente dice "eve no responde" | el cerebro no está arrancado, o está en otro puerto |
| `401` al hablarle | producción sin token → falta `KIRA_AGENT_TOKEN` en `brain/.env.local` |
| Cambié instrucciones y no pasa nada | estás en producción; usa `eve dev` o recompila |
| Kira no reacciona a "Oye Kira" | mira el log: ¿transcribió mal? ¿se cortó la frase? |
| Corta antes de que termines de hablar | `SILENCE_STOP_MS` en `src/main.cpp` |
| Kira contesta pero no se oye | ¿está el parlante en la carcasa? Es lo que más cambia |
| El parlante hace ruido raro | no debería: GPIO 27 va forzado a LOW. Si vuelve, avisa |

### Los logs

En modo desarrollo, las dos terminales muestran todo.

En producción:

```
logs\brain.log      el cerebro
logs\bridge.log     el puente
```

Y en la terminal del puente, esta línea es telemetría de calibración del micrófono:

```
  nivel    240 | ruido    121 | voz>   363 | fin<   217
```

`nivel` es lo que oye ahora, `ruido` el fondo que ha medido, y `voz>` / `fin<` los umbrales
que calcula solo. Si el `nivel` en silencio queda pegado a `voz>`, se disparará con cualquier
ruido.

---

## Limpieza de vez en cuando

Cada vez que arranca, el cerebro restaura las conversaciones antiguas:

```
[world-local] Re-enqueued 42 active run(s) on startup
```

Son inofensivas (están aparcadas esperando), pero crecen. Para borrarlas, con Kira parada:

```powershell
stop_kira.cmd
rmdir /s /q brain\.eve\.workflow-data
```

Se pierde el historial de conversaciones viejas. Nada más.
