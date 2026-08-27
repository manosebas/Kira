# ROADMAP — Proyecto Kira

Estado del proyecto y lo que falta, en pasos sencillos.

Los detalles técnicos están en `CLAUDE.md`.

**Leyenda:** ✅ hecho y probado físicamente · 🔨 en curso · ⬜ pendiente

---

## Cómo arrancar Kira hoy

Doble clic, o desde una terminal en la carpeta del proyecto:

```
run_brain.cmd     el cerebro (los agentes)
run_bridge.cmd    el puente (microfono, voz, parlante)
```

Ninguno abre ventana visible. Los logs quedan en `logs\brain.log` y `logs\bridge.log`.

Para pararla —**obligatorio antes de subir firmware**, porque el puente tiene COM5 tomado:

```
stop_kira.cmd
```

---

## Dónde estamos

**Kira ya escucha, piensa con agentes y responde por su parlante.**

Le dices *"Oye Kira, ¿cuál es la capital de Colombia?"* y contesta *"Bogotá."* por el altavoz,
pasando por transcripción local, orquestador de agentes y voz sintetizada.

Lo que falta para que sea un producto: **una cara** (la pantalla), **agentes que hagan cosas
de verdad** (correo, calendario, casa), y que **arranque sola al encender la computadora**.

---

## Fase 1 — Hardware ✅ COMPLETADA

- ✅ ESP32 programable y estable
- ✅ Micrófono INMP441 soldado y validado
- ✅ Amplificador MAX98357A soldado y validado
- ✅ Parlante conectado y funcionando
- ✅ Micrófono y parlante funcionando **a la vez** en un solo firmware
- ✅ Parlante **montado en la carcasa impresa** (fue la mayor mejora de volumen)
- ✅ Volumen ajustado hasta el límite razonable

---

## Fase 2 — Que Kira oiga y hable ✅ COMPLETADA

- ✅ Capturar audio del micrófono y detectar cuándo empiezas y terminas de hablar
- ✅ Enviar el audio a la computadora
- ✅ Transcribir a texto con **faster-whisper** local (gratis, sin internet)
- ✅ Detectar la palabra de activación **"Oye Kira"** y quedarse solo con la instrucción
- ✅ Convertir la respuesta a voz con **SAPI5** de Windows (gratis)
- ✅ Reproducir esa voz por el parlante
- ✅ Varias frases seguidas sin reiniciar nada

---

## Fase 3 — Agentes ✅ COMPLETADA (la base)

- ✅ Orquestador **eve** instalado y corriendo en la propia PC (sin depender de la nube)
- ✅ Agente raíz con la personalidad de Kira y reglas de voz
- ✅ Primer subagente de prueba, y verificado que el enrutado **funciona y discrimina**
- ✅ Memoria de conversación: *"¿y la de Perú?"* se resuelve por contexto
- ✅ Bucle completo: **voz → agentes → voz**

---

## Fase 4 — Salir a producción 🔨 CASI COMPLETA

**Objetivo: enciendes la computadora y Kira funciona. Sin abrir terminales, sin comandos.**

- ✅ **Autenticación del canal de eve.**
  Era el bloqueo: `eve start` devolvía 401 por la autenticación de relleno del scaffold.
  Ahora usa un token compartido con el puente. Sin esto no había producción posible.

- ✅ **`requirements.txt`** con las dependencias de Python fijadas.

- ✅ **Modo producción funcionando** (`eve build` + `eve start`), verificado con el ciclo
  completo hasta el parlante.

- ✅ **Arranque sin ventanas de consola.** Tres scripts:
  `run_brain.cmd`, `run_bridge.cmd`, `stop_kira.cmd`.

- ✅ **El puente espera al cerebro** en vez de rendirse. Sin esto, en un arranque en frío
  las dos partes arrancan a la vez, el puente gana la carrera y se moría.

- ⬜ **Registrar las tareas programadas de Windows** — *aplazado a propósito, ver abajo.*

- ⬜ **Probar el arranque en frío**: reiniciar la computadora, no tocar nada, y decir
  "Oye Kira". (Depende del punto anterior.)

- ⬜ **Manejo de fallos.** Si el cerebro no responde o el ESP32 se desconecta, que Kira lo
  diga por el parlante en vez de quedarse muda.

- ⬜ **Pasar el repositorio a privado** antes de guardar cualquier credencial:
  `gh repo edit manosebas/Kira --visibility private`

### ⏸ APLAZADO — registrar el arranque automático

**Decidido: hacerlo cuando el proyecto esté terminado, no ahora.**

**Por qué se aplaza:** una vez registradas, las tareas toman **COM5 en cada inicio de
sesión**. Las fases 6 y 7 (pantalla y Wi-Fi) van a pedir muchos uploads de firmware, y cada
upload fallaría hasta ejecutar `stop_kira.cmd`. No vale la pena esa fricción todavía.

**Mientras tanto:** arrancar Kira a mano con `run_brain.cmd` y `run_bridge.cmd`.

**Cuando el proyecto esté terminado**, ejecutar una sola vez (como Administrador):

```powershell
$K = "C:\Users\Administrador\Documents\Cosas\PROYECTOS\Kira"
schtasks /create /tn "Kira Brain"  /tr "'$K\run_brain.cmd'"  /sc onlogon /rl highest /f
schtasks /create /tn "Kira Bridge" /tr "'$K\run_bridge.cmd'" /sc onlogon /rl highest /f
```

Comprobar con `schtasks /query /tn "Kira Brain"`, y quitarlas con
`schtasks /delete /tn "Kira Brain" /f` si estorban.

Después: **reiniciar, no tocar nada, y decir "Oye Kira"**. Ese es el examen final de la fase.

---

## Fase 5 — Agentes reales ⬜ PENDIENTE

**Aquí empieza el valor de verdad.** Hoy Kira responde preguntas; en esta fase empieza a
*hacer cosas*.

- ⬜ **Decidir qué agentes queremos** y qué hace cada uno.
  Ideas: correo, calendario, casa (luces), notas y recordatorios, música.

- ⬜ **Agente de correo.** Leer, buscar y enviar.
  Un solo subagente con varias herramientas, no uno por acción: cada subagente necesita su
  propia conexión a Gmail y duplicar eso no aporta nada.

- ⬜ **Agente de calendario.** Consultar la agenda, crear eventos.

- ⬜ **Pedir confirmación antes de actuar.** Enviar un correo o apagar algo no debería pasar
  sin que Kira pregunte primero. eve trae aprobaciones para esto.

- ⬜ **Agente de casa** (luces, enchufes), cuando haya hardware que controlar.

- ⬜ **Quitar el subagente de prueba** cuando ya no haga falta.

---

## Fase 6 — La cara de Kira ⬜ PENDIENTE

Kira hoy no tiene expresión: no se sabe si está escuchando, pensando o esperando.

- ⬜ **Comprar la pantalla OLED SH1107** de 1.5", 128×128, SPI de 7 pines.
  **Todavía no está comprada**, y hasta que llegue no se escribe código que dependa de ella.

- ⬜ **Conectar la pantalla.** Son 7 cables. Antes hay que verificar el pinout real contra el
  módulo físico: dos pantallas que parecen iguales pueden tener los pines en otro orden.
  Quedan libres GPIO suficientes; 25, 26, 27 y 33 están ocupados por el audio y no se tocan.

- ⬜ **Dibujar los ojos.** Una cara simple que se pueda animar.

- ⬜ **Programar los estados visuales:**
  - en reposo (parpadeo de vez en cuando)
  - escuchando
  - pensando
  - hablando
  - error

- ⬜ **Sincronizar la cara con lo que pasa de verdad.** El firmware ya sabe cuándo detecta
  voz y cuándo reproduce audio; la cara debe engancharse a eso.

---

## Fase 7 — Kira sin cables ⬜ PENDIENTE

Hoy Kira necesita estar conectada por USB a la computadora. Esta fase la libera.

- ⬜ **Conectar el ESP32 al Wi-Fi.**
  Las credenciales nunca van en el código: mecanismo aparte y fuera del repositorio.

- ⬜ **Decidir cómo viaja el audio** hacia el backend (HTTP, WebSocket, streaming) y en qué
  formato. **Todavía sin decidir.**

- ⬜ **Mover el cerebro fuera de la PC**, si conviene.

- ⬜ **Decidir si STT y TTS pasan a la nube.**
  Serían más rápidos y sonarían mejor, pero cuestan dinero y hoy son gratis. No está decidido.

- ⬜ **Alimentación propia**, para que no dependa del USB de la computadora.

---

## Fase 8 — Producto terminado ⬜ PENDIENTE

- ⬜ Reducir la latencia (hoy Kira espera 3 segundos de silencio antes de empezar a pensar)
- ⬜ Wake word en el propio ESP32, en vez de transcribir todo para descartarlo luego
- ⬜ Interrumpir a Kira mientras habla
- ⬜ Ajustar la carcasa: pantalla, botón, acceso al cable
- ⬜ Que sobreviva a los casos raros: sin internet, sin cerebro, micrófono tapado

---

## Decisiones aún abiertas

Cosas que **no hay que dar por supuestas** en ninguna sesión de trabajo:

| Tema | Estado |
|---|---|
| Proveedor final de STT | sin decidir (hoy: faster-whisper local) |
| Proveedor final de TTS | sin decidir (hoy: SAPI5 de Windows) |
| Wake word definitivo | sin decidir (hoy: regex sobre la transcripción) |
| Transporte de audio hacia la nube | sin decidir |
| Qué agentes tendrá Kira | sin decidir |
| Pinout de la pantalla OLED | sin verificar (hardware no comprado) |
