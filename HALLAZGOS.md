# HALLAZGOS — Auditoría del proyecto Kira

**Fecha:** 2026-08-26
**Alcance:** revisión completa del repositorio tal como está hoy.
**Estado de este documento:** solo hallazgos. Las recomendaciones y mejoras se tratarán después.

> ⚠ **DOCUMENTO HISTÓRICO — PARCIALMENTE SUPERADO (2026-08-27).**
> `CLAUDE.md` manda sobre este archivo. Lo que ya cambió desde esta auditoría:
> - La cadena STT (`ESP32 → PC → faster-whisper → wake word`) **sí llegó a funcionar**.
> - El MAX98357A y el parlante **están conectados y validados** (tono 440 Hz).
> - La cadena TTS completa (`PC → serial → ESP32 → I2S → parlante`) **está validada**:
>   `speak.py` reprodujo "Hola, soy Kira." correctamente.
> - `src/main.cpp` fue sustituido por el receptor de audio, así que el firmware de captura
>   descrito en la sección 2 de este documento **ya no existe como código** (ver 3.8 de CLAUDE.md).
> - El baud del proyecto es ahora **921600** en los tres componentes, así que la incompatibilidad
>   del punto 6 de la sección 5 **está resuelta**.
>
> Sigue vigente: **no hay git** y **no hay `requirements.txt`**.

---

## 1. Inventario real del repositorio

```
Kira/
├── CLAUDE.md          <- fuente de verdad del proyecto
├── HALLAZGOS.md       <- este archivo
├── platformio.ini     <- config funcional (esp32doit-devkit-v1, arduino, 115200)
├── listen.py          <- pipeline de PC (NO estaba documentado en CLAUDE.md)
├── .gitignore         <- existe, pero NO hay repositorio git inicializado
├── .vscode/
├── include/           <- vacío (solo README por defecto)
├── lib/               <- vacío (solo README por defecto)
├── src/
│   └── main.cpp       <- firmware I2S + detección de voz
├── test/              <- vacío (solo README por defecto)
└── .pio/              <- artefactos de build
```

Hallazgo: el proyecto tiene **dos piezas de software**, no una. CLAUDE.md solo describía una.

---

## 2. Pieza 1 — Firmware `src/main.cpp` (validado en hardware)

Qué hace, paso a paso:

1. Inicializa el driver I2S (`driver/i2s.h`) en `I2S_NUM_0`, modo master + RX.
2. Pines: `SCK = GPIO 26`, `WS = GPIO 25`, `SD = GPIO 33`.
3. Parámetros: 16 kHz, `I2S_BITS_PER_SAMPLE_32BIT`, `I2S_CHANNEL_FMT_ONLY_RIGHT`,
   `I2S_COMM_FORMAT_I2S`, `dma_buf_count = 4`, `dma_buf_len = 256`.
4. Lee bloques de 256 muestras `int32_t` con `i2s_read(..., portMAX_DELAY)`.
5. Calcula nivel: `sample >>= 14`, promedia el valor absoluto del bloque, resta `NOISE_FLOOR (300)`,
   satura en 0.
6. Máquina de estados de voz con histéresis:
   - 3 bloques consecutivos con nivel >= `VOICE_THRESHOLD (250)` → `>>> VOZ INICIADA`.
   - 6 bloques consecutivos con nivel <= `SILENCE_THRESHOLD (80)` → `<<< VOZ FINALIZADA`.
7. Imprime el estado y el nivel como **texto plano** por Serial a **115200**.
8. `delay(100)` al final del loop, por lo que cada bloque equivale a ~100 ms.

**Hallazgo clave: el firmware NUNCA transmite audio.** Solo detecta actividad de voz y la loguea.

---

## 3. Pieza 2 — `listen.py` (no documentado, mucho más avanzado)

Pipeline que corre en la PC:

1. Abre el puerto serie **`COM5` a 921600 baud**.
2. Espera un **protocolo binario** con framing propio:
   - MAGIC: `0xAA 0x55`
   - tipo de frame: 1 = START, 2 = AUDIO, 3 = END
   - longitud: `uint16` little-endian
   - payload
3. Al recibir START limpia el buffer; con AUDIO acumula PCM; con END cierra la captura.
4. Escribe el buffer a un WAV temporal: **mono, 16 kHz, `setsampwidth(2)` = 16 bits**.
5. Transcribe con **faster-whisper**, modelo `small`, `device="cpu"`, `compute_type="int8"`,
   `language="es"`, `beam_size=5`, `vad_filter=True`.
6. Normaliza el texto (minúsculas, quita acentos) y busca la wake word por regex:
   `\boye kira\b`, `\boye, kira\b`, `\boie kira\b`.
7. Si la detecta, recorta el prefijo "Oye Kira" conservando el texto original.
8. Envía el resto a `send_to_fake_api()`: **API SIMULADA**, con `time.sleep(0.8)` y una respuesta
   de string fabricada. No hay `requests`, no hay backend real.
9. Descarta la frase si no contiene la wake word.

---

## 4. HALLAZGO CRÍTICO — firmware y script son incompatibles

`listen.py` no puede funcionar con el firmware actual. Cuatro incompatibilidades simultáneas:

| Aspecto | `src/main.cpp` | `listen.py` |
|---|---|---|
| Baud rate | 115200 | **921600** |
| Formato de salida | texto `Serial.println` | frames binarios `AA 55` |
| Audio | nunca sale del ESP32 | espera payloads PCM |
| Ancho de muestra | `int32_t` sin convertir | `setsampwidth(2)` = `int16` |

Falta la capa intermedia: un firmware que convierta int32 → int16, empaquete los frames
START / AUDIO / END y transmita a 921600.

Consecuencia: **la cadena STT + wake word está escrita pero nunca se ha probado end-to-end**,
porque nunca le llega audio.

---

## 5. Desviaciones respecto a lo documentado en CLAUDE.md

1. **`listen.py` no figura en CLAUDE.md.** La estructura del repo documentada está incompleta.
2. **CLAUDE.md dice que el proveedor de STT "no está decidido"**, pero el código ya eligió
   faster-whisper local en la PC.
3. **CLAUDE.md dice que el wake word "no tiene implementación decidida"**, pero ya existe una
   implementación por regex sobre la transcripción completa.
4. **`COM5` está hardcodeado** en `listen.py`, lo que contradice la regla explícita de no
   hardcodear el puerto.
5. **Desviación arquitectónica:** el plan es wake word y STT fuera del ESP32 pero *en la nube*.
   Hoy están en una PC conectada por USB. Es aceptable como prototipo, pero significa que
   ahora mismo Kira **depende de un PC con cable** y no es un dispositivo autónomo.
6. **El baud 921600 de `listen.py` choca** con `monitor_speed = 115200` de `platformio.ini`.

---

## 6. Riesgos de proyecto

1. **No hay git.** Existe `.gitignore` pero no `.git`. La baseline de hardware validada
   (pines, canal RIGHT, calibración) no tiene ningún punto de retorno. Es el riesgo mayor.
2. **No hay `requirements.txt`.** Las dependencias de `listen.py` (`pyserial`, `faster-whisper`)
   no están declaradas en ningún sitio.
3. **La calibración (`NOISE_FLOOR 300`, umbrales 250/80) es específica del entorno actual.**
   Otro cuarto o distinta distancia al micro pueden romperla.
4. **El API es simulada.** No existe backend, ni orquestador de agentes, ni TTS.

---

## 7. Estado real por etapas del roadmap

| Etapa | Estado real |
|---|---|
| ESP32 programable y estable | ✅ validado físicamente |
| Micrófono I2S conectado | ✅ soldado y validado |
| Captura I2S validada localmente | ✅ silencio / aplausos / voz |
| Detección de inicio y fin de voz | ✅ funcionando con histéresis |
| Transporte de audio ESP32 → PC | ❌ protocolo definido en la PC, no implementado en el firmware |
| STT | 🟡 escrito (faster-whisper), nunca ejecutado end-to-end |
| Wake word | 🟡 escrito (regex sobre transcripción), nunca ejecutado end-to-end |
| Salida de audio (MAX98357A + parlante) | ❌ no conectado |
| Wi-Fi | ❌ |
| Backend / orquestador de agentes | ❌ solo API simulada |
| TTS | ❌ |
| OLED SH1107 | ❌ hardware no presente |

---

## 8. Distinción importante

Siguiendo la regla del proyecto de no confundir estados:

- **Compilado correctamente:** firmware I2S.
- **Subido correctamente:** firmware I2S.
- **Probado físicamente:** micrófono, captura I2S, detección de voz.
- **Escrito pero NUNCA ejecutado con datos reales:** todo `listen.py`.

---

*Fin de los hallazgos. Las recomendaciones y el plan de mejora se documentarán aparte.*
