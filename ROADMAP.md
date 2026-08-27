# ROADMAP — Proyecto Kira

Estado del proyecto y lo que falta, en pasos sencillos.

Los detalles técnicos están en `CLAUDE.md`.

**Leyenda:** ✅ hecho y probado físicamente · 🔨 en curso · ⬜ pendiente

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

## Fase 4 — Salir a producción ⬜ SIGUIENTE

**Objetivo: enciendes la computadora y Kira funciona. Sin abrir terminales, sin comandos.**

Hoy hay que arrancar dos cosas a mano cada vez. Eso es lo que hay que quitar.

- ⬜ **Poner autenticación al canal de eve.**
  Hoy solo funciona el modo de desarrollo (`eve dev`). El modo de producción (`eve start`)
  responde 401 porque el scaffold trae una autenticación de relleno. Sin esto no hay
  producción. Es un archivo: `brain/agent/channels/eve.ts`.

- ⬜ **Anotar las dependencias de Python** en un `requirements.txt`.
  Ahora mismo están instaladas "porque sí". Si algo se rompe o cambias de máquina, no hay
  forma de reinstalarlas.

- ⬜ **Compilar eve para producción** (`eve build`) y comprobar que `eve start` aguanta un
  uso normal, no solo que arranca.

- ⬜ **Crear dos tareas programadas de Windows**, con disparador *"al iniciar sesión"*:
  una para el cerebro (`eve start`) y otra para el puente (`kira_bridge.py`).
  Usar `pythonw` en vez de `python` para que no aparezca ninguna ventana negra.

- ⬜ **Probar el arranque en frío**: reiniciar la computadora, no tocar nada, y decir
  "Oye Kira".

- ⬜ **Manejo de fallos.** Si el cerebro no responde o el ESP32 se desconecta, que Kira lo
  diga por el parlante en vez de quedarse muda.

- ⬜ **Pasar el repositorio a privado** antes de guardar cualquier credencial:
  `gh repo edit manosebas/Kira --visibility private`

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
