# USO — Chuleta

## Cómo ejecuto los comandos

Abre la terminal en VS Code: **Ctrl + Ñ** (o menú *Terminal → New Terminal*). Se abre ya en
la carpeta del proyecto. Es PowerShell.

Los `.cmd` **necesitan el `.\` delante**. PowerShell no ejecuta archivos de la carpeta actual
sin él:

```powershell
.\stop_kira.cmd      ✅
stop_kira.cmd        ❌ "El termino 'stop_kira.cmd' no se reconoce..."
```

Doble clic en el Explorador también funciona, pero la ventana se cierra sola y no ves errores.
Mejor la terminal.

Para **parar** algo que corre en una terminal: **Ctrl + C** en esa terminal.

---

## Qué hago en cada caso

| Quiero... | Comando |
|---|---|
| **Desarrollar agentes** (terminal 1) | `cd brain` y luego `npm exec -- eve dev --no-ui` |
| **Desarrollar agentes** (terminal 2) | `python kira_bridge.py` |
| **Probar agentes sin hablar** | `cd brain` y luego `npm exec -- eve dev` |
| **Solo usar Kira** | `.\run_brain.cmd` y luego `.\run_bridge.cmd` |
| **Parar todo** | `.\stop_kira.cmd` |
| **Subir firmware** | `.\stop_kira.cmd` → `platformio run --target upload` → `python kira_bridge.py` |
| **Solo compilar firmware** | `platformio run` |
| **Recompilar el cerebro** (tras cambios, en producción) | `cd brain` y luego `npm exec -- eve build` |
| **Ver los logs de producción** | `type logs\bridge.log` · `type logs\brain.log` |

---

## Qué necesita reinicio y qué no

Con `eve dev` corriendo:

| Cambio | ¿Reiniciar? |
|---|---|
| Texto de `instructions.md` (raíz o subagente) | **No.** Efecto en la frase siguiente |
| Crear un subagente nuevo | **No.** Lo detecta en vivo |
| `agent.ts`, `channels/eve.ts`, `npm install`, `.env.local` | Sí, Ctrl+C y arrancar |
| `kira_bridge.py` | Sí, Ctrl+C en su terminal |
| `src/main.cpp` | Sí, y hay que subir firmware |

En modo **producción** (`run_brain.cmd`) nada recarga: hay que `eve build` y arrancar de nuevo.

---

## Si algo falla

| Síntoma | Qué hacer |
|---|---|
| El upload de firmware falla | `.\stop_kira.cmd` — el puente tiene COM5 tomado |
| "puerto 2000 ocupado" | `.\stop_kira.cmd` — ya hay un cerebro corriendo |
| "eve no responde" | Arranca el cerebro primero |
| `401` al hablarle | Falta `KIRA_AGENT_TOKEN` en `brain/.env.local` |
| Cambié instrucciones y no pasa nada | Estás en producción. Usa `eve dev` |
| Delega al subagente equivocado | Arregla su `description`: es lo único que el raíz lee |
| Kira contesta pero no se oye | ¿El parlante está en la carcasa? |

---

## Las dos piezas

**El cerebro** (agentes) ocupa el puerto **2000**.
**El puente** (micrófono, voz, parlante) ocupa **COM5**.

Todo corre en tu PC. Los dos modos del cerebro usan el mismo puerto, así que **nunca corras
`eve dev` y `run_brain.cmd` a la vez**.

| | `eve dev` | `run_brain.cmd` |
|---|---|---|
| Recarga al guardar | sí | no |
| Ventana | sí, ves todo | no, silenciosa |
| Para qué | desarrollar | usar |

---

## Limpieza ocasional

Si el log del cerebro dice `Re-enqueued N active run(s)` y N crece mucho:

```powershell
.\stop_kira.cmd
rmdir /s /q brain\.eve\.workflow-data
```

Borra el historial de conversaciones viejas. Nada más.
