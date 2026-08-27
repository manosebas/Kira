# CLAUDE.md — Proyecto Kira

Este archivo es la **fuente de verdad** para cualquier sesión futura de Claude Code trabajando en este repositorio.
Léelo completo antes de proponer o realizar cualquier cambio.

**Última actualización:** 2026-08-27

---

## 1. Qué es Kira

Kira será un pequeño **dispositivo físico de escritorio** que funciona como **terminal de voz** para un sistema de agentes de IA.

**Kira NO es el cerebro de IA.** El ESP32 no ejecuta agentes localmente. Es una interfaz física (micrófono, parlante, pantalla) conectada a servicios externos.

### Flujo final deseado

1. El usuario dice **"Oye Kira"**.
2. Kira detecta la wake word.
3. Kira empieza a escuchar.
4. Kira detecta una pausa suficientemente larga para determinar que el usuario terminó de hablar.
5. El audio se procesa / transcribe (**la arquitectura definitiva de STT todavía NO está decidida**).
6. Se envía la petición al backend.
7. Un **orquestador de agentes** construido con Vercel AI SDK / infraestructura relacionada procesa la petición.
8. Los agentes necesarios realizan las acciones.
9. Se genera una respuesta.
10. La respuesta se convierte a voz mediante **TTS**.
11. Kira reproduce la respuesta por su parlante.

La inteligencia, los agentes, la memoria, las herramientas, el razonamiento y (si corresponde) STT/TTS viven **fuera** del ESP32.

La **pantalla** sirve principalmente como cara / estado visual: ojos, animaciones, escuchando, pensando, hablando, error. Puede mostrar texto simple cuando sea útil.

---

## 2. Arquitectura

### 2.1 Arquitectura objetivo (final)

```
┌──────────────────────────┐       Wi-Fi        ┌────────────────────────────┐
│  KIRA (ESP32)            │  <-------------->  │  BACKEND (nube)            │
│  terminal ligero         │                    │  sistema inteligente       │
│                          │                    │                            │
│  - INMP441 (mic, I2S in) │  audio saliente    │  - STT (proveedor TBD)     │
│  - MAX98357A + parlante  │  ---------------> │  - Orquestador de agentes  │
│    (I2S out)             │                    │    (Vercel AI SDK)         │
│  - OLED SH1107 (cara)    │  audio/respuesta   │  - Memoria / herramientas  │
│  - Wake word + VAD       │  <--------------- │  - TTS (proveedor TBD)     │
└──────────────────────────┘                    └────────────────────────────┘
```

### 2.2 Arquitectura REAL de hoy (prototipo)

```
┌──────────────────────────┐   USB serial 921600   ┌────────────────────────────┐
│  KIRA (ESP32)            │  <----------------->  │  PC WINDOWS                │
│                          │                       │                            │
│  - INMP441  (I2S RX)     │   PCM entrante        │  - listen.py               │
│  - MAX98357A + parlante  │   ------------------> │    faster-whisper (STT)    │
│    (I2S TX)              │                       │    wake word por regex     │
│                          │   PCM saliente        │    API SIMULADA (local)    │
│                          │  <------------------  │  - speak.py                │
│                          │                       │    pyttsx3 + FFmpeg (TTS)  │
└──────────────────────────┘                       └────────────────────────────┘
```

**Importante:** hoy Kira **no es autónoma**. Depende de un PC conectado por cable USB.
No hay Wi-Fi, no hay nube, no hay backend real. Esto es aceptable como prototipo, pero
no confundirlo con la arquitectura objetivo.

Reglas arquitectónicas:

- El ESP32 se mantiene como **terminal ligero**.
- El backend (hoy: la PC) es el **sistema inteligente**.
- **No** implementar agentes de IA dentro del ESP32.
- El transporte final de audio hacia la nube (HTTP, WebSocket, streaming, formato) **todavía no está definido**.
- El wake word definitivo **todavía no está decidido** (hoy es regex sobre la transcripción, en la PC).
- Los proveedores finales de STT y TTS **no están elegidos** (hoy: faster-whisper local y pyttsx3 local).

---

## 3. Estado real verificado

Leyenda estricta, no mezclar niveles:

- ✅ **PROBADO EN HARDWARE** — el usuario lo ejecutó físicamente y funcionó.
- 🟡 **ESCRITO Y COMPILA / EJECUTA, SIN VALIDAR FÍSICAMENTE** — el código está, la prueba física no.
- ❌ **NO EXISTE / NO PROBADO**.

### 3.1 Software / toolchain

| Elemento | Estado |
|---|---|
| SO de desarrollo | Windows 11 Pro |
| Editor | Visual Studio Code |
| Sistema de build | PlatformIO Core **6.1.19** ✅ |
| Plataforma | **Espressif 32 7.0.1** ✅ |
| Lenguaje firmware | C++ / **Arduino para ESP32** ✅ |
| Ejecutable PlatformIO | `C:\Users\Administrador\.platformio\penv\Scripts\platformio.exe` (ya en el PATH) ✅ |
| Python de la PC | **3.13.7** ✅ |
| pyserial | **3.5** ✅ |
| FFmpeg | **9.0.1-full_build-www.gyan.dev**, en el PATH ✅ |
| STT en PC | `faster-whisper`, modelo `small`, CPU, int8 ✅ |
| TTS en PC | `pyttsx3` (SAPI5 de Windows) ✅ |
| `pydub` | **descartado a propósito.** Python 3.13 eliminó `audioop`. No reintroducirlo. |
| Control de versiones | ❌ **NO hay repositorio git inicializado** (existe `.gitignore`, no existe `.git`) |

### 3.2 `platformio.ini` (funcional — no cambiar sin autorización)

```ini
[env:esp32doit-devkit-v1]
platform = espressif32
board = esp32doit-devkit-v1
framework = arduino
monitor_speed = 921600
```

**Sobre el baud 921600:** antes era 115200. Se cambió con razón técnica explícita: el transporte
de PCM mono 16 bits a 16 kHz necesita **32 000 B/s**, y 115200 baud solo dan ~11 500 B/s.
`listen.py` y `speak.py` también usan 921600. El comentario dentro de `platformio.ini`
explica cómo volver atrás.

### 3.3 Hardware verificado

- Chip identificado por esptool: **ESP32-D0WD-V3 revision v3.1** ✅
- Crystal 40 MHz, flash 4 MB, dual core 240 MHz, Wi-Fi + Bluetooth ✅
- Dev board ESP-WROOM-32 de 30 pines, USB-C ✅
- Windows la reconoce como **USB-SERIAL CH340** ✅
- Aparece como **COM5** en esta computadora — **NO asumir que COM5 será siempre el puerto** ✅
- Carcasa impresa en 3D disponible ✅

### 3.4 Inventario de componentes

| Componente | Estado |
|---|---|
| ESP32 ESP-WROOM-32, 30 pines, USB-C, CH340, 4 MB | ✅ presente y validado |
| Micrófono INMP441 (MEMS digital I2S) | ✅ presente, soldado y validado |
| Amplificador/DAC MAX98357A (I2S) | ✅ presente, soldado y validado |
| Parlante 4 Ω / 3 W / ~40 mm | ✅ presente, soldado y validado |
| Pantalla OLED SH1107 1.5" 128×128 SPI 7 pines | ❌ **NO comprada / no presente** |
| Mini protoboard 170 puntos | ✅ |
| Jumpers M–M, M–H, H–H | ✅ |
| Headers 2×3 pines | ✅ |
| Cautín regulable, estaño, flux | ✅ |
| Cable USB-C ↔ USB-C | ✅ |

### 3.5 Qué está PROBADO EN HARDWARE ✅

1. ESP32 programable, firmware persistente en flash tras desconexión física.
2. **Entrada de audio:** captura I2S real del INMP441 — silencio, aplausos y voz distinguibles.
3. Detección de **inicio y fin de voz** con histéresis y piso de ruido calibrado.
4. **Grabación de la frase completa en RAM** y cálculo de su duración.
5. **Cadena STT completa en prototipo:** `INMP441 → ESP32 → serial → PC → faster-whisper → texto`.
6. **Wake phrase por software:** detectar `"Oye Kira"`, recortarlo, quedarse solo con la instrucción
   útil y pasarla a una **API simulada local**.
   Ejemplo real: entrada `Oye Kira, prende la luz de mi cuarto` → texto útil `prende la luz de mi cuarto`.
7. **Salida de audio:** `ESP32 → I2S TX → MAX98357A → parlante` reproduciendo un **tono seno de 440 Hz
   generado internamente por el ESP32**. Sonó correctamente.
8. **TTS en la PC:** `pyttsx3 → FFmpeg → WAV mono PCM signed 16-bit LE 16 kHz`. Formato verificado:
   `Canales: 1 / Bits: 16 / Sample rate: 16000`. Voz **Microsoft Helena Desktop (español de España)**,
   `rate = 165`. Medición real de `"Hola, soy Kira."`: 2.10 s, 67 174 bytes, 66 bloques de 1024 B,
   pico 21 095 / 32 767 (sin clipping).
9. **CADENA TTS COMPLETA `PC → serial → ESP32 → I2S → MAX98357A → parlante`** con el
   **protocolo v2** (sección 6). Se ejecutó `python speak.py` y el parlante dijo
   **"Hola, soy Kira."** de forma clara e inteligible. Sin cortes, sin ruido, sin corrupción.
   Esto era el fallo abierto del 2026-08-26 y **está resuelto**.

**Consecuencia crítica del punto 7:** el hardware de salida de audio (amplificador, soldaduras,
bornera, parlante, cableado I2S) está **descartado como causa de fallos**. Mientras esa prueba
del tono siga siendo válida, **no volver a investigar hardware** cuando el audio suene mal.

### 3.6 Qué está ESCRITO pero SIN VALIDAR FÍSICAMENTE 🟡

- **Reproducción de varias frases seguidas sin reiniciar el ESP32.** El firmware está escrito
  para soportarlo (vuelve a reposo tras `DONE`), pero solo se ha probado **una frase por ejecución**.
- **Recuperación ante error del protocolo** (`NAK`, reenvío de bloque, `ABORT`). El camino
  feliz está validado; los caminos de error no se han provocado a propósito.

Nada más queda en este estado: `src/main.cpp` y `speak.py` ya están validados en hardware (ver 3.5).

### 3.7 Qué NO existe / NO está probado ❌

- Pantalla OLED SH1107: **no comprada**. No escribir código que dependa de ella.
- Wi-Fi.
- Cualquier comunicación con un backend real.
- Backend / orquestador de agentes: hoy solo hay una función local simulada en `listen.py`.
- STT y TTS en la nube.
- Entrada y salida de audio funcionando **a la vez** (ver 5.4: hoy son firmwares distintos).

### 3.8 RIESGO ABIERTO — código validado que se perdió

`src/main.cpp` fue **sobrescrito** por el receptor de audio. Consecuencia:

- El firmware de **captura del micrófono + detección de voz** (etapas 3, 4 y 16 del roadmap)
  **ya no existe como código fuente en este repositorio**. Solo sobreviven sus parámetros,
  documentados en la sección 4 de este archivo y en `HALLAZGOS.md`.
- El firmware que enviaba frames `AA 55` a `listen.py` (y que hizo funcionar la cadena STT)
  **tampoco existe** en el repositorio.
- **No hay git**, así que no hay punto de retorno.

Esto es el mayor riesgo del proyecto ahora mismo. Antes de seguir avanzando conviene:
1. inicializar git y comprometer el estado actual;
2. reconstruir el firmware del micrófono en un archivo aparte que no compita con `main.cpp`.

**No borrar ni sobrescribir más código validado sin haber guardado antes una copia.**

---

## 4. Hardware pin map

Regla obligatoria: **cada vez que se asigne físicamente un GPIO, se documenta aquí en el mismo cambio.**

### 4.0 Resumen de GPIO ocupados

| GPIO | Uso | Dirección | Estado |
|---|---|---|---|
| 25 | WS (mic) **y** LRC (amplificador) — reloj de palabra **compartido** | clock out | ✅ VALIDADO |
| 26 | SCK (mic) **y** BCLK (amplificador) — reloj de bit **compartido** | clock out | ✅ VALIDADO |
| 27 | DIN del MAX98357A — datos de **salida** | out | ✅ VALIDADO |
| 33 | SD del INMP441 — datos de **entrada** | in | ✅ VALIDADO |

Los relojes se comparten a propósito (el ESP32 es master en ambos casos). Solo las líneas de
**datos** están separadas: 33 entra, 27 sale. **No reasignar 25, 26, 27 ni 33.**

### 4.1 Micrófono INMP441 — ✅ BASELINE VALIDADA EN HARDWARE

| Pin del módulo | Conexión en el ESP32 | Estado |
|---|---|---|
| VDD | **3V3** (nunca 5 V) | ✅ VALIDADO |
| GND | **GND** | ✅ VALIDADO |
| SD (datos serie) | **GPIO 33** | ✅ VALIDADO |
| SCK (bit clock) | **GPIO 26** | ✅ VALIDADO |
| WS (word select) | **GPIO 25** | ✅ VALIDADO |
| L/R (selección de canal) | **GND** | ✅ VALIDADO |

Configuración I2S de entrada validada:

```cpp
#define I2S_WS   25
#define I2S_SD   33
#define I2S_SCK  26
#define I2S_PORT I2S_NUM_0
```

```cpp
.sample_rate = 16000
.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT
.channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT
.communication_format = I2S_COMM_FORMAT_I2S
```

**Canal RIGHT — no "corregir" a LEFT.**
Aunque `L/R` está a `GND` (lo que en teoría implicaría LEFT), las pruebas reales con este
módulo demostraron que el audio solo llega con `I2S_CHANNEL_FMT_ONLY_RIGHT`.
Con `ONLY_LEFT` las muestras eran permanentemente `0`. **La medición manda sobre la teoría.**

**Sobre la advertencia de deprecación:** PlatformIO avisa que `I2S_COMM_FORMAT_I2S` está
*deprecated*. Es una advertencia, **no un error**: compila, sube y funciona.
**No migrar la API I2S solo para silenciar esa advertencia** durante el prototipo.

### 4.2 Pruebas físicas del micrófono

Con canal LEFT, de forma permanente:

```text
Min: 0 | Max: 0 | Rango: 0
```

Al cambiar a RIGHT aparecieron inmediatamente muestras reales:

1. **Silencio** — rangos crudos de ~5–15 millones.
2. **Aplausos** — picos de decenas o cientos de millones.
3. **Voz humana** — niveles sostenidos claramente por encima del silencio.

Conclusión: **micrófono, soldaduras, alimentación, cableado e interfaz I2S son FUNCIONALES.**

### 4.3 Normalización de nivel (calibrada)

```cpp
sample >>= 14;          // reduce la escala enorme de los datos I2S de 32 bits
#define NOISE_FLOOR 300 // piso de ruido observado en este entorno
```

Salida típica obtenida:

```text
Silencio
Silencio
Ruido suave: 143
Voz/sonido: 368
Voz/sonido: 385
Silencio
```

### 4.4 Detección de voz (histéresis) — valores calibrados

```cpp
#define NOISE_FLOOR 300
#define VOICE_THRESHOLD 250
#define SILENCE_THRESHOLD 80
#define VOICE_BLOCKS_TO_START 3
#define SILENCE_BLOCKS_TO_STOP 6
```

- La voz debe superar `VOICE_THRESHOLD` durante varios bloques consecutivos para declararse **iniciada**.
- Ya hablando, se usa un umbral **inferior** (`SILENCE_THRESHOLD`) para detectar el final → histéresis.
- Se exigen varios bloques consecutivos de silencio antes de dar por terminada la intervención.

Motivo: evita falsos inicios por ruidos aislados y evita cortar una frase por pausas cortas.
Estos valores están **calibrados en este entorno concreto** (este cuarto, esta distancia al micro).

### 4.5 MAX98357A + parlante — ✅ BASELINE VALIDADA EN HARDWARE

| Pin del módulo | Conexión en el ESP32 | Estado |
|---|---|---|
| VIN | **VIN** del ESP32 (~5 V desde USB) | ✅ VALIDADO |
| GND | **GND** común | ✅ VALIDADO |
| BCLK (bit clock) | **GPIO 26** (compartido con SCK del mic) | ✅ VALIDADO |
| LRC (word select) | **GPIO 25** (compartido con WS del mic) | ✅ VALIDADO |
| DIN (datos serie) | **GPIO 27** | ✅ VALIDADO |
| GAIN | **sin conectar** (ganancia por defecto) | ✅ VALIDADO |
| SD (shutdown/mode) | **sin conectar** | ✅ VALIDADO |
| Salida `+` | positivo del parlante | ✅ VALIDADO |
| Salida `-` | negativo del parlante | ✅ VALIDADO |

Este módulo va a **VIN (5 V)**, no a 3V3: es un amplificador y necesita la tensión para dar
potencia al parlante. El parlante **nunca** se conecta directo al ESP32.

Configuración I2S de salida validada con el tono de 440 Hz:

```cpp
#define I2S_BCLK 26
#define I2S_LRC  25
#define I2S_DOUT 27
#define SAMPLE_RATE 16000
```

```cpp
.mode = I2S_MODE_MASTER | I2S_MODE_TX
.sample_rate = 16000
.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT
.channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT   // mono duplicado a L/R
.communication_format = I2S_COMM_FORMAT_I2S
```

El MAX98357A es mono, pero se le entrega el flujo estéreo con la **misma muestra en L y R**.

### 4.6 OLED SH1107 128×128 1.5" (SPI, 7 pines) — hardware NO presente

| Pin del módulo | GPIO del ESP32 | Estado |
|---|---|---|
| VCC | — | NO ASIGNADO / hardware no presente |
| GND | — | NO ASIGNADO / hardware no presente |
| SCL / SCK | — | NO ASIGNADO / hardware no presente |
| SDA / MOSI | — | NO ASIGNADO / hardware no presente |
| RES / RST | — | NO ASIGNADO / hardware no presente |
| DC | — | NO ASIGNADO / hardware no presente |
| CS | — | NO ASIGNADO / hardware no presente |

**No inventar asignaciones.** El pinout real de cada módulo se verifica contra el módulo físico
(foto o serigrafía) antes de indicar ninguna conexión. Dos módulos físicamente similares
pueden tener pinouts distintos.

---

## 5. Software del proyecto

El proyecto tiene **tres piezas de software**, no una.

```
Kira/
├── CLAUDE.md          <- este archivo (fuente de verdad)
├── HALLAZGOS.md       <- auditoría del 2026-08-26 (parcialmente superada, ver nota)
├── platformio.ini     <- config funcional
├── listen.py          <- PC: serie -> WAV -> faster-whisper -> wake word -> API simulada
├── speak.py           <- PC: texto -> pyttsx3 -> FFmpeg -> PCM -> serie -> ESP32
├── .gitignore
├── .vscode/
├── include/           <- vacío
├── lib/               <- vacío
├── src/
│   └── main.cpp       <- FIRMWARE ACTUAL: receptor de PCM + reproducción I2S
├── test/              <- vacío
└── .pio/              <- artefactos de build (ignorado)
```

`speaker_test.py` **fue eliminado** el 2026-08-27. Era un script temporal de diagnóstico.
No volver a crear scripts temporales: todo diagnóstico va dentro de `speak.py` o `listen.py`.

**Nota sobre `HALLAZGOS.md`:** es la auditoría del 2026-08-26. Sigue siendo útil como historia,
pero varias de sus conclusiones ya están superadas (la cadena STT sí llegó a funcionar después,
y la salida de audio ya está conectada y validada). **Este `CLAUDE.md` manda sobre `HALLAZGOS.md`.**

### 5.1 `src/main.cpp` — firmware de SALIDA de audio (actual) — ✅ VALIDADO

Qué hace:

1. Inicializa I2S en `I2S_NUM_0`, modo **master + TX**, 16 kHz, 16 bits, `RIGHT_LEFT`.
2. Deja el TX **parado** en reposo (`i2s_stop`) para que el parlante no sisee.
3. Escucha el puerto serie a 921600 y parsea el **protocolo v2** (sección 6).
4. Por cada bloque de PCM mono: lo duplica a L/R y lo escribe con `i2s_write(..., portMAX_DELAY)`.
5. Contesta **ACK después** de escribir en I2S → el DAC marca el ritmo del envío.
6. Al recibir `END` empuja 200 ms de silencio (para que salga la cola del audio) y contesta `DONE`.
7. Queda listo para la siguiente frase **sin reiniciar el ESP32**.

Detalles que importan:

- `Serial.setRxBufferSize(8192)` **antes** de `Serial.begin()`. El buffer por defecto de 256 B
  era una de las causas del audio corrupto.
- DMA: `dma_buf_count = 12`, `dma_buf_len = 512` → ~384 ms de audio adelantado.
  Es el colchón que absorbe los parones del scheduler de Windows.
- Único texto que emite el firmware: `KIRA-TTS READY` al arrancar. Todo lo demás son
  tokens binarios de 1–2 bytes, para que los logs no rompan nunca el parser.

### 5.2 `speak.py` — TTS de la PC hacia el parlante — ✅ VALIDADO

Flujo: `texto → pyttsx3 → WAV → FFmpeg → PCM mono 16-bit LE 16 kHz → serie → ESP32`.

- Texto fijo por ahora: `text = "Hola, soy Kira."`
- Fuerza la voz española (`VOICE_MATCH = "ES-"`). Sin esto Windows usa **Zira (inglés)**
  y la frase sale con acento inglés.
- Conversión **directa con FFmpeg**, sin `pydub`.
- Verifica el WAV resultante (canales, bits, sample rate) antes de enviar; si no cuadra, aborta.
- Controla DTR/RTS a mano y **provoca el reset del ESP32 a propósito** para partir siempre
  del mismo estado.
- Descubre al ESP32 con `PING`/`READY` reintentado, no esperando un `READY` único.
- Envía bloques de 1024 B y espera el ACK de cada uno.
- Mensajes: `ESP32 listo`, `Enviando audio...`, `Reproduciendo...`, `Reproducción completada`.
- Cierra el puerto siempre (`finally`) y borra los WAV temporales.
- Constante `VOLUME` (por defecto `1.0`) para subir ganancia por software vía FFmpeg si hace falta.

### 5.3 `listen.py` — STT de la PC (⚠ sin firmware que lo alimente)

Pipeline: `serie → frames AA 55 → WAV → faster-whisper → wake word → API simulada`.

- Puerto `COM5` a 921600, framing propio: MAGIC `0xAA 0x55`, tipo (1=START, 2=AUDIO, 3=END), `uint16` de longitud.
- Whisper `small`, CPU, int8, `language="es"`, `beam_size=5`, `vad_filter=True`.
- Wake word por regex sobre el texto normalizado: `oye kira`, `oye, kira`, `oie kira`.
- `send_to_fake_api()` es **una función local simulada**, no hay backend.

**⚠ Estado: `listen.py` no puede funcionar hoy.** El firmware actual (`main.cpp`) es de SALIDA
de audio y no envía frames `AA 55`. El firmware de captura que sí lo hacía se perdió (ver 3.8).

### 5.4 Entrada y salida NO conviven todavía

El micrófono lee a **32 bits** y el amplificador escribe a **16 bits** en el **mismo puerto**
`I2S_NUM_0`, que solo admite un `bits_per_sample`. Por eso hoy son **dos firmwares distintos**,
no dos funciones del mismo firmware.

Cuando toque unificarlos, las opciones reales son:

- usar `I2S_NUM_1` para uno de los dos (los relojes seguirían compartidos por cableado);
- o alternar: reconfigurar el puerto entre modo escucha y modo habla (Kira no necesita
  oír y hablar a la vez).

Decidirlo cuando lleguemos ahí. **No improvisarlo ahora.**

---

## 6. Protocolo serial PC ↔ ESP32 (v2, salida de audio)

Diseñado el 2026-08-27 para resolver los fallos de la v1.
**✅ VALIDADO EN HARDWARE el 2026-08-27:** `python speak.py` reprodujo `"Hola, soy Kira."`
correctamente por el parlante. Este protocolo es ahora una **baseline estable**.

### 6.1 Por qué falló la v1 (no repetir estos errores)

1. **Protocolos incompatibles.** `speak.py` enviaba frames `AA 55 tipo len16` (el protocolo
   de `listen.py`, dirección contraria) mientras el firmware esperaba `"KIRA" + uint32`.
   El ESP32 nunca veía la `'K'`. **`speak.py` no podía funcionar nunca.** El tono sí sonaba
   porque `speaker_test.py` sí usaba el protocolo correcto.
2. **Desborde del RX serial.** El buffer por defecto de `Serial` es 256 B. Mientras el firmware
   estaba bloqueado en `i2s_write`, seguían entrando 32 000 B/s → bytes perdidos.
3. **Sin checksum ni resincronización.** Un solo byte perdido desplaza todo el flujo un byte:
   las muestras `int16` quedan mal alineadas y suenan como ruido brutal. Esa era la
   causa directa del "sonido feo".
4. **`time.sleep(0.016)` no existe en Windows.** La granularidad del timer es ~15.6 ms, así que
   dormía 16–31 ms y se enviaba **más lento que tiempo real** → underrun de DMA → clicks.
5. **`READY` se perdía.** El firmware solo lo emitía si `Serial.available() == 0`: cualquier
   byte de basura lo silenciaba para siempre.
6. **Bytes `\x00` antes de `READY`.** Es el boot ROM del ESP32 imprimiendo a 115200 y leído
   a 921600. Es normal, hay que descartarlo, no interpretarlo.
7. **Reset indeterminado al abrir COM.** El CH340 mueve DTR/RTS al abrir el puerto y reinicia
   el ESP32 en un momento impredecible.

### 6.2 Frame PC → ESP32

```
0xA5 0x5A  CMD  SEQ  LEN_LO LEN_HI  payload[LEN]  CK_LO CK_HI
```

- `CK` = suma de 16 bits (LE) de `CMD + SEQ + LEN_LO + LEN_HI +` todos los bytes de payload.
- `LEN` máximo: **1024** (512 muestras = 32 ms de audio).
- Cualquier byte que no encaje con el sync se descarta: la basura del bootloader no puede
  confundir al parser.

| CMD | Nombre | Payload | Respuesta |
|---|---|---|---|
| `0x01` | PING | — | `READY` |
| `0x02` | BEGIN | `uint32` LE con el total de bytes de PCM | `ACK` + SEQ |
| `0x03` | DATA | PCM mono `int16` LE | `ACK` + SEQ (después de escribir en I2S) |
| `0x04` | END | — | `DONE` (cuando la cola de audio ya salió) |
| `0x05` | ABORT | — | `ACK` + SEQ |

### 6.3 Tokens ESP32 → PC

| Byte | Significado |
|---|---|
| `0x06` | ACK (seguido de 1 byte con el SEQ confirmado) |
| `0x15` | NAK (checksum inválido o frame incompleto → la PC reenvía el mismo SEQ) |
| `0x21` | READY |
| `0x22` | DONE |
| `0x23` | ERR (comando inesperado o payload inválido) |

Durante la transferencia el ESP32 **no emite texto**: solo estos tokens. Así los logs
no pueden romper el parser.

### 6.4 Decisiones de diseño y su motivo

| Decisión | Motivo |
|---|---|
| **ACK después de `i2s_write`** | El DAC marca el ritmo. Nada de temporizadores adivinados, imposible desbordar el RX. |
| **`SEQ` en cada frame** | Si se pierde un ACK, la PC reenvía; el firmware detecta el duplicado y **no reproduce dos veces**. |
| **Checksum de 16 bits** | Un frame corrupto se descarta entero y se reenvía. Nunca entra basura al DAC. |
| **`setRxBufferSize(8192)`** | Absorbe ráfagas mientras el firmware está bloqueado en I2S. |
| **DMA 12 × 512** | ~384 ms de colchón: los primeros bloques se aceptan al instante (prellenado) y los parones de Windows no provocan underrun. |
| **Reset deliberado por RTS** | El reset ocurre cuando la PC lo decide, no por sorpresa. |
| **`PING` reintentado** | No depende de capturar un `READY` emitido una sola vez. |
| **`i2s_stop` en reposo** | Sin siseo en el parlante entre frases. |
| **Silencio de cierre antes de `DONE`** | `DONE` significa de verdad "ya se oyó todo", no "ya recibí todo". |

Márgenes: el enlace serie da ~92 kB/s y el audio consume 32 kB/s → factor ~2.9 de holgura.

---

## 7. Flujo de trabajo

### Uso normal (sin PC para el firmware)

Conectar alimentación → el ESP32 arranca y ejecuta el último firmware grabado en flash.
**VS Code NO es necesario para que el firmware corra.** (Pero hoy la inteligencia está en la PC,
así que Kira sí necesita el PC para hacer algo útil.)

### Desarrollo del firmware

1. Editar código.
2. **PlatformIO Build** — compila y verifica. No toca la placa.
3. **PlatformIO Upload** — compila y escribe el firmware al ESP32.
4. **PlatformIO Serial Monitor** — observa los logs. **No** programa la placa.

Serial Monitor a **921600 baud** (ver 3.2).
**Cerrar el Serial Monitor antes de ejecutar `speak.py` o `listen.py`:** el puerto COM
no se puede compartir.

### Desarrollo en la PC

```powershell
python speak.py     # texto -> voz por el parlante
python listen.py    # voz -> texto (requiere el firmware de captura, hoy inexistente)
```

### Peculiaridad de esta placa al hacer Upload

Si esptool no conecta solo:

```
Failed to connect to ESP32: No serial data received.
```

La secuencia que funciona, **durante el mensaje "Connecting..."**:

1. Mantener presionado **BOOT**.
2. Presionar y soltar **EN**.
3. Seguir manteniendo **BOOT**.
4. Cuando esptool reconoce el ESP32, soltar **BOOT**.

Un intento mostró `Invalid head of packet (0x78): Possible serial noise or corruption.`
y el segundo intento inmediato completó el upload verificando hashes.
**No concluir por eso que el hardware está defectuoso.**

---

## 8. Filosofía de desarrollo y trato con el usuario

El usuario **está aprendiendo electrónica desde cero** y quiere **construir y entender** el
proyecto, no recibir código terminado.

Por tanto:

- No asumir conocimientos previos de electrónica.
- Explicar qué hace cada componente **antes** de conectarlo.
- Explicar qué significan VCC, GND, GPIO, I2S, etc. la primera vez que aparezcan.
- Dar instrucciones físicas **extremadamente claras**, **pin por pin**.
- Antes de sugerir conexiones eléctricas, comprobar voltajes y pinout.
- Distinguir claramente pines de alimentación, tierra y señal.
- Evitar cualquier conexión que pueda dañar el ESP32 o los módulos.
- **No improvisar pinouts.** Si no se conoce con exactitud el pinout de un módulo, pedir foto.
- No asumir que dos módulos físicamente similares tienen el mismo pinout.

Al trabajar interactivamente con hardware:

- Avanzar paso a paso, **un solo paso físico importante a la vez**.
- Esperar confirmación cuando haya riesgo físico o cuando una prueba dependa de la anterior.
- No abrumar con diez pasos futuros cuando el usuario está ejecutando el primero.

---

## 9. Roadmap incremental

**No intentar implementar Kira completa de una vez.**

| # | Etapa | Estado |
|---|---|---|
| 1 | ESP32 programable y estable | ✅ COMPLETADO |
| 2 | Entender protoboard y GPIO | ✅ COMPLETADO |
| 3 | Conectar INMP441 | ✅ COMPLETADO (soldado y validado) |
| 4 | Validar captura I2S del micrófono | ✅ COMPLETADO (silencio / aplausos / voz) |
| 5 | Conectar MAX98357A y parlante | ✅ COMPLETADO (soldado y cableado, ver 4.5) |
| 6 | Validar reproducción de audio | ✅ COMPLETADO (tono seno 440 Hz interno) |
| 7 | Validar entrada y salida de audio juntas | ❌ pendiente (ver 5.4: hoy son firmwares separados) |
| 8 | Grabar la frase completa en RAM | ✅ COMPLETADO |
| 9 | Transporte de audio ESP32 → PC | ✅ COMPLETADO en su día — ⚠ **firmware perdido** (ver 3.8) |
| 10 | Speech-to-Text (faster-whisper en PC) | ✅ COMPLETADO como prototipo |
| 11 | Wake word "Oye Kira" (regex en PC) | ✅ COMPLETADO como prototipo |
| 12 | TTS en la PC (pyttsx3 + FFmpeg) | ✅ COMPLETADO |
| 13 | Reproducir TTS de la PC en el parlante | ✅ COMPLETADO (protocolo v2, validado 2026-08-27) |
| 14 | Inicializar git y proteger las baselines | ⬅️ **SIGUIENTE / NECESARIO** (ver 3.8) |
| 15 | Reconstruir el firmware de captura perdido | ⬅️ **NECESARIO** (ver 3.8) |
| 16 | Unificar escucha + habla en un firmware | pendiente |
| 17 | Conectar Wi-Fi | pendiente |
| 18 | Comunicación ESP32 ↔ backend real | pendiente |
| 19 | Backend / orquestador de agentes (Vercel AI SDK) | pendiente |
| 20 | STT / TTS en la nube | pendiente |
| 21 | Integrar OLED SH1107 cuando esté comprada | pendiente (hardware no presente) |
| 22 | Estados visuales y animaciones | pendiente |
| 23 | Optimización, manejo de errores y producto final | pendiente |

### Objetivo inmediato

La etapa 13 está cerrada: Kira ya **habla**. Lo siguiente, por orden de riesgo:

1. **Etapa 14 — git.** Es lo más urgente. Hay dos baselines validadas en hardware
   (`main.cpp` de salida y `speak.py`) sin ningún punto de retorno, y ya se perdió una así (3.8).
2. **Etapa 15 — reconstruir el firmware de captura** para que `listen.py` vuelva a tener
   quien lo alimente.
3. **Etapa 16 — unificar escuchar y hablar** (ver 5.4: hoy son firmwares separados por el
   conflicto 32 bits / 16 bits en `I2S_NUM_0`).

Si en algún momento el audio de salida suena mal, el problema está en el software/protocolo,
**no en el hardware** (ver 3.5, puntos 7 y 9).

---

## 10. Reglas estrictas para Claude Code

1. Antes de modificar archivos, **inspeccionar el estado actual del repositorio**.
2. **No reemplazar configuraciones funcionales** por preferencias personales.
3. **No migrar** a ESP-IDF, MicroPython u otro framework sin autorización explícita.
4. **No cambiar la definición de placa** (`board = esp32doit-devkit-v1`) sin autorización.
5. **No cambiar el baud rate de 921600** sin razón explícita (la razón del cambio desde 115200
   está documentada en 3.2).
6. **No borrar código funcional** sin explicar primero por qué **y sin guardar una copia**
   (ver el riesgo de 3.8: ya se perdió una baseline validada así).
7. Hacer cambios **pequeños, verificables y reversibles**.
8. Después de cambios importantes, **compilar** antes de asumir que funcionan.
9. **No declarar que el hardware funciona** hasta que el usuario haya hecho la prueba física.
10. Diferenciar **siempre**: *compila* / *subido* / *probado físicamente*.
11. **No almacenar** API keys, contraseñas de Wi-Fi ni secretos en archivos versionados.
12. Cuando lleguemos a credenciales, diseñar un mecanismo local seguro y añadirlo al `.gitignore`.
13. El ESP32 tiene **recursos limitados**: evitar dependencias pesadas.
14. Mantener la arquitectura: **ESP32 = terminal ligero, backend = sistema inteligente**.
15. **No implementar agentes de IA dentro del ESP32.**
16. **No asumir** todavía qué proveedor final se usará para STT o TTS.
17. **No asumir** que el wake word definitivo será el regex actual.
18. **No asumir que la OLED está instalada.** No está comprada.
19. **No asignar GPIO al azar**: mantener el mapa de la sección 4 actualizado.
20. Cuando se asigne un GPIO físicamente, **documentarlo en la sección 4 en el mismo cambio**.
21. **No crear scripts temporales de diagnóstico.** Todo diagnóstico va dentro de `speak.py`
    o `listen.py`, o como logs del propio protocolo.
22. **No usar `pydub`** ni ninguna librería que dependa de `audioop` (Python 3.13 lo eliminó).

### Regla de protección de las baselines validadas

Antes de tocar cualquiera de estos puntos hay que **explicar por qué es necesario y dejar
una forma sencilla de volver atrás**:

**Entrada de audio (INMP441):**
- GPIO 25, 26, 33 · alimentación 3.3 V · `L/R` a GND
- canal `I2S_CHANNEL_FMT_ONLY_RIGHT` · 16 kHz · lectura de 32 bits
- `NOISE_FLOOR 300`, `VOICE_THRESHOLD 250`, `SILENCE_THRESHOLD 80` y los contadores de bloques

**Salida de audio (MAX98357A):**
- GPIO 25, 26, 27 · alimentación por **VIN (5 V)** · GAIN y SD sin conectar
- 16 kHz · 16 bits · `I2S_CHANNEL_FMT_RIGHT_LEFT` con la muestra mono duplicada

**Protocolo v2 de salida de audio (validado 2026-08-27):**
- Framing `0xA5 0x5A CMD SEQ LEN CK` y el **ACK después de `i2s_write`**.
  Ese orden ES el control de flujo: no invertirlo ni "optimizarlo".
- `Serial.setRxBufferSize(8192)` **antes** de `Serial.begin()`.
- `dma_buf_count = 12`, `dma_buf_len = 512` (~384 ms de colchón).
- `CHUNK_BYTES = 1024` en `speak.py` == `MAX_PAYLOAD` en el firmware. **Deben coincidir.**
- Baud 921600 en ambos lados.
- No volver a temporizar el envío con `time.sleep()`: fue una de las causas del fallo original.

**General:**
- `I2S_COMM_FORMAT_I2S` y su advertencia de deprecación: **no migrar la API solo por la advertencia**.
- No "arreglar" en frío algo que las pruebas físicas demostraron que funciona (caso RIGHT vs LEFT).
- No reestructurar componentes ya validados si no es necesario para la siguiente funcionalidad.

### Reglas de entorno

- No reintroducir hacks de rutas locales de PlatformIO dentro del proyecto. El ejecutable ya está
  en el PATH; la extensión de VS Code usa `"platformio-ide.useBuiltinPIOCore": true`.
- No hardcodear `COM5` para la **subida** de firmware: dejar que PlatformIO autodetecte el puerto.
  (En `speak.py` y `listen.py` `COM5` sigue hardcodeado; es deuda técnica conocida, pendiente de
  autodetección.)
