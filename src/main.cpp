// ======================================================
// KIRA — Firmware UNIFICADO (escuchar + hablar)
//
// Un solo firmware con dos modos sobre I2S_NUM_0:
//
//   MODO ESCUCHA  (por defecto al arrancar)
//     INMP441 -> I2S RX 32 bits -> deteccion de voz (VAD)
//     -> frames "AA 55" con PCM int16 hacia la PC
//
//   MODO HABLA    (se entra al recibir BEGIN)
//     PC -> protocolo v2 -> I2S TX 16 bits -> MAX98357A
//
// Por que dos modos y no los dos a la vez: el microfono
// lee a 32 bits y el amplificador escribe a 16, y un
// puerto I2S solo admite un bits_per_sample. Se reinstala
// el driver al cambiar de modo. Kira no necesita oir y
// hablar al mismo tiempo, y ademas asi no se oye a si misma.
//
// Cableado (NO modificar — validado en hardware):
//   BCLK/SCK -> GPIO 26   (compartido mic + amplificador)
//   LRC/WS   -> GPIO 25   (compartido mic + amplificador)
//   DIN      -> GPIO 27   (salida, exclusivo del amplificador)
//   SD       -> GPIO 33   (entrada, exclusivo del microfono)
// ======================================================

#include <Arduino.h>
#include "driver/i2s.h"


// ======================================================
// CONFIG
// ======================================================

#define SERIAL_BAUD      921600
#define SERIAL_RX_BUFFER 8192     // 256 B por defecto era insuficiente

#define I2S_PORT I2S_NUM_0

#define I2S_BCLK 26
#define I2S_LRC  25
#define I2S_DOUT 27
#define I2S_SD   33

#define SAMPLE_RATE 16000

// Colchon de DMA: 12 * 512 frames estereo = 6144 frames
// = ~384 ms de audio adelantado. Absorbe los parones
// del scheduler de Windows sin underrun.
#define DMA_BUF_COUNT 12
#define DMA_BUF_LEN   512

// Payload maximo por frame: 1024 B = 512 muestras = 32 ms
#define MAX_PAYLOAD 1024

// Silencio de cierre para garantizar que la cola de audio
// termina de salir antes de contestar DONE.
#define TAIL_SILENCE_SAMPLES 3200  // 200 ms


// ======================================================
// CONFIG DEL MICROFONO
// ======================================================

// Muestras por bloque de captura: 512 * 32 bits = 2048 B
// leidos, que producen 512 int16 = 1024 B = 32 ms.
#define MIC_BLOCK_SAMPLES 512

// Escala del nivel: el nivel de un bloque es la media de
// abs(raw >> LEVEL_SHIFT).
#define LEVEL_SHIFT 14

// Umbrales ADAPTATIVOS, calculados sobre el ruido de fondo
// medido en vivo.
//
// Por que adaptativos y no los 250/80 fijos de CLAUDE.md:
// esos numeros venian de otra metrica de nivel. Medidos con
// la media de absolutos, la voz de este microfono da del
// orden de 4000, asi que un umbral de silencio de 80 es
// inalcanzable: la frase no terminaba nunca y siempre
// cortaba por el tope de 12.8 s. Medido en hardware
// 2026-08-27.
#define VOICE_FACTOR_NUM    30   // inicio de voz = ruido * 3.0
#define VOICE_FACTOR_DEN    10
#define SILENCE_FACTOR_NUM  18   // fin de voz    = ruido * 1.8
#define SILENCE_FACTOR_DEN  10

// Suelos absolutos: en una habitacion muy silenciosa evitan
// que el umbral baje tanto que cualquier crujido dispare.
#define VOICE_FLOOR_MIN    250
#define SILENCE_FLOOR_MIN   80

// Bloques de voz seguidos para declarar que empezo a hablar.
// 3 * 32 ms = ~96 ms. Suficiente para no arrancar con un golpe
// aislado, y corto para no perder el inicio de la palabra.
#define VOICE_BLOCKS_TO_START 3

// Pausa de silencio que cierra la frase.
//
// ESTE ES EL NUMERO QUE AJUSTA "CUANTO ESPERA KIRA A QUE
// TERMINES DE HABLAR". Es tambien latencia: Kira no empieza a
// pensar hasta que pasa esta pausa, asi que se suma a lo que
// tardas en oir la respuesta.
//
// Era 192 ms (6 bloques) y cortaba al instante en cuanto el
// usuario respiraba. 3 s es lo que se pidio tras la prueba del
// 2026-08-27. Si se hace pesado, 1000-1500 ms suele ser el
// punto dulce para dictado normal.
#define SILENCE_STOP_MS 3000

#define SILENCE_BLOCKS_TO_STOP \
  ((SILENCE_STOP_MS) / ((MIC_BLOCK_SAMPLES) * 1000 / (SAMPLE_RATE)))

// Peso del ruido de fondo nuevo en la media movil, en 1/16.
// 1/16 = se adapta en ~1 s, lo bastante lento para que la
// propia voz no lo arrastre hacia arriba.
#define NOISE_EMA_SHIFT 4

// Ganancia del audio que se envia a la PC. El INMP441
// entrega 24 bits utiles alineados a la izquierda dentro
// de 32.
//
// Historial medido en hardware el 2026-08-27:
//   11 -> recorte (pico 32768/32767)
//   13 -> picos tipicos 12822-21080, pero una frase hablada
//         de cerca volvio a recortar (32768)
//   14 -> elegido. Picos esperados ~6000-10500, de sobra para
//         Whisper y con margen para hablar fuerte o de cerca.
//
// El recorte importa mas que el nivel: distorsiona la forma de
// onda y empeora la transcripcion. Es mejor quedarse corto.
//
// COMO AJUSTARLO: el frame VOICE_END lleva el pico de la
// frase (0..32767). Si el pico se queda por debajo de
// ~3000, baja el shift en 1. Si toca 32767 (recorte),
// sube el shift en 1.
#define MIC_SHIFT 14

// Cada cuantos bloques se manda telemetria de nivel.
// 16 bloques * 32 ms = ~0.5 s.
#define LEVEL_REPORT_BLOCKS 16

// Pre-roll: bloques guardados ANTES de declarar inicio de
// voz. Sin esto se recorta el arranque de "Oye" y la wake
// word no se detecta.
#define PREROLL_BLOCKS VOICE_BLOCKS_TO_START

// Tope de duracion de una frase, por seguridad.
#define MAX_PHRASE_BLOCKS 400   // 400 * 32 ms = 12.8 s


// ======================================================
// PROTOCOLO PC -> ESP32 (v2, salida de audio)
// ======================================================

#define SYNC0 0xA5
#define SYNC1 0x5A

#define CMD_PING  0x01
#define CMD_BEGIN 0x02
#define CMD_DATA  0x03
#define CMD_END   0x04
#define CMD_ABORT 0x05

#define TOK_ACK   0x06
#define TOK_NAK   0x15
#define TOK_READY 0x21
#define TOK_DONE  0x22
#define TOK_ERR   0x23

// Tiempo maximo para completar un frame ya empezado.
#define FRAME_TIMEOUT_MS 1500


// ======================================================
// PROTOCOLO ESP32 -> PC (entrada de audio)
// ======================================================
//
//   0xAA 0x55  TIPO  LEN_LO LEN_HI  payload[LEN]
//
// Sin checksum: es el formato que ya consumia el lado de
// la PC, y un byte perdido aqui solo degrada la
// transcripcion, no destruye el audio como pasaba en la
// direccion contraria.
//
#define UP_MAGIC0 0xAA
#define UP_MAGIC1 0x55

#define UP_START 1
#define UP_AUDIO 2
#define UP_END   3
#define UP_LEVEL 4   // telemetria: nivel actual + ruido de fondo


// ======================================================
// ESTADO
// ======================================================

enum AudioMode {
  MODE_NONE,
  MODE_LISTEN,
  MODE_SPEAK
};

static AudioMode audioMode = MODE_NONE;

// Ultimo codigo de error del driver I2S, para poder decir
// POR QUE fallo un cambio de modo en vez de solo "ERR".
static esp_err_t lastI2sError = ESP_OK;

// Buffers globales: no en la pila, para no arriesgar
// desbordarla dentro del loop.
static uint8_t payloadBuffer[MAX_PAYLOAD];
static int16_t stereoBuffer[MAX_PAYLOAD];   // 512 muestras -> 1024 int16

static int32_t micRaw[MIC_BLOCK_SAMPLES];
static int16_t micPcm[MIC_BLOCK_SAMPLES];
static int16_t preRoll[PREROLL_BLOCKS][MIC_BLOCK_SAMPLES];

static uint8_t  preRollCount   = 0;   // bloques validos en el pre-roll
static uint8_t  preRollHead    = 0;   // siguiente posicion a escribir

static bool     recording      = false;
static uint16_t voiceBlocks    = 0;
static uint16_t silenceBlocks  = 0;
static uint16_t phraseBlocks   = 0;
static uint16_t phrasePeak     = 0;

// Ruido de fondo medido en vivo. -1 = todavia sin medir.
static int32_t  noiseFloor     = -1;
static uint16_t levelCountdown = 0;

static bool     sessionActive  = false;
static bool     i2sRunning     = false;
static uint32_t expectedBytes  = 0;
static uint32_t receivedBytes  = 0;
static uint8_t  lastSeq        = 0;
static bool     haveLastSeq    = false;


// ======================================================
// UTILIDADES SERIAL
// ======================================================

static bool readByteTimeout(uint8_t &out, uint32_t timeoutMs) {

  uint32_t start = millis();

  while (millis() - start < timeoutMs) {

    int value = Serial.read();

    if (value >= 0) {
      out = (uint8_t)value;
      return true;
    }
  }

  return false;
}


static bool readExactTimeout(uint8_t *buffer, size_t length, uint32_t timeoutMs) {

  size_t   received = 0;
  uint32_t start    = millis();

  while (received < length) {

    if (millis() - start >= timeoutMs) {
      return false;
    }

    int available = Serial.available();

    if (available <= 0) {
      continue;
    }

    size_t chunk = Serial.readBytes(
      buffer + received,
      length - received
    );

    received += chunk;
  }

  return true;
}


static inline void sendToken(uint8_t token) {

  Serial.write(token);
  Serial.flush();
}


static inline void sendAck(uint8_t seq) {

  uint8_t response[2] = { TOK_ACK, seq };

  Serial.write(response, 2);
  Serial.flush();
}


// Frame de subida: ESP32 -> PC
static void sendUpFrame(uint8_t type, const uint8_t *payload, uint16_t length) {

  uint8_t header[5];

  header[0] = UP_MAGIC0;
  header[1] = UP_MAGIC1;
  header[2] = type;
  header[3] = (uint8_t)(length & 0xFF);
  header[4] = (uint8_t)((length >> 8) & 0xFF);

  Serial.write(header, 5);

  if (length > 0 && payload != NULL) {
    Serial.write(payload, length);
  }
}


// ======================================================
// I2S — INSTALACION POR MODO
// ======================================================

static void i2sUninstall() {

  if (audioMode == MODE_NONE) {
    return;
  }

  i2s_zero_dma_buffer(I2S_PORT);
  i2s_stop(I2S_PORT);
  i2s_driver_uninstall(I2S_PORT);

  // El driver libera sus buffers DMA y su interrupcion de forma
  // asincrona. Reinstalar en el mismo tick puede devolver
  // ESP_ERR_INVALID_STATE o ESP_ERR_NO_MEM. Este margen es
  // imperceptible al oido y hace el cambio de modo fiable.
  delay(20);

  audioMode  = MODE_NONE;
  i2sRunning = false;
}


// Modo HABLA: TX, 16 bits, mono duplicado a L/R.
static bool i2sInstallSpeak() {

  if (audioMode == MODE_SPEAK) {
    return true;
  }

  i2sUninstall();

  i2s_config_t config = {

    .mode = (i2s_mode_t)(
      I2S_MODE_MASTER |
      I2S_MODE_TX
    ),

    .sample_rate = SAMPLE_RATE,

    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,

    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,

    .communication_format = I2S_COMM_FORMAT_I2S,

    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,

    .dma_buf_count = DMA_BUF_COUNT,

    .dma_buf_len = DMA_BUF_LEN,

    .use_apll = false,

    .tx_desc_auto_clear = true,

    .fixed_mclk = 0
  };

  i2s_pin_config_t pins = {

    .bck_io_num   = I2S_BCLK,
    .ws_io_num    = I2S_LRC,
    .data_out_num = I2S_DOUT,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };

  lastI2sError = i2s_driver_install(I2S_PORT, &config, 0, NULL);

  if (lastI2sError != ESP_OK) {
    return false;
  }

  lastI2sError = i2s_set_pin(I2S_PORT, &pins);

  if (lastI2sError != ESP_OK) {
    i2s_driver_uninstall(I2S_PORT);
    return false;
  }

  i2s_zero_dma_buffer(I2S_PORT);

  // En reposo el TX queda parado: sin siseo en el parlante.
  i2s_stop(I2S_PORT);

  audioMode  = MODE_SPEAK;
  i2sRunning = false;

  return true;
}


// Modo ESCUCHA: RX, 32 bits, canal RIGHT.
//
// Canal RIGHT a proposito. Con L/R del modulo a GND la
// teoria dice LEFT, pero la medicion real con este modulo
// dio muestras permanentemente 0 en LEFT. La medicion
// manda sobre la teoria: NO "corregir" esto.
static bool i2sInstallListen() {

  if (audioMode == MODE_LISTEN) {
    return true;
  }

  i2sUninstall();

  i2s_config_t config = {

    .mode = (i2s_mode_t)(
      I2S_MODE_MASTER |
      I2S_MODE_RX
    ),

    .sample_rate = SAMPLE_RATE,

    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,

    .channel_format = I2S_CHANNEL_FMT_ONLY_RIGHT,

    .communication_format = I2S_COMM_FORMAT_I2S,

    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,

    .dma_buf_count = DMA_BUF_COUNT,

    .dma_buf_len = DMA_BUF_LEN,

    .use_apll = false,

    .tx_desc_auto_clear = false,

    .fixed_mclk = 0
  };

  i2s_pin_config_t pins = {

    .bck_io_num   = I2S_BCLK,
    .ws_io_num    = I2S_LRC,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_SD
  };

  // CRITICO: dejar DIN del amplificador en LOW fijo.
  //
  // En modo escucha el I2S no conduce GPIO 27, pero BCLK y LRC
  // siguen activos porque los comparte con el microfono. Con DIN
  // flotando, el MAX98357A lee basura y la reproduce: eso eran
  // los "sonidos raros aleatorios" del parlante (medido en
  // hardware 2026-08-27). Forzado a 0 el amplificador recibe
  // silencio digital.
  //
  // i2s_set_pin con data_out_num = I2S_PIN_NO_CHANGE no toca
  // este pin, asi que la configuracion manual se mantiene.
  pinMode(I2S_DOUT, OUTPUT);
  digitalWrite(I2S_DOUT, LOW);

  lastI2sError = i2s_driver_install(I2S_PORT, &config, 0, NULL);

  if (lastI2sError != ESP_OK) {
    return false;
  }

  lastI2sError = i2s_set_pin(I2S_PORT, &pins);

  if (lastI2sError != ESP_OK) {
    i2s_driver_uninstall(I2S_PORT);
    return false;
  }

  i2s_zero_dma_buffer(I2S_PORT);
  i2s_start(I2S_PORT);

  audioMode  = MODE_LISTEN;
  i2sRunning = true;

  return true;
}


static void resetVad() {

  recording     = false;
  voiceBlocks   = 0;
  silenceBlocks = 0;
  phraseBlocks  = 0;
  phrasePeak    = 0;
  preRollCount  = 0;
  preRollHead   = 0;
}


// ======================================================
// I2S — SALIDA
// ======================================================

static void i2sEnsureStarted() {

  if (i2sRunning) {
    return;
  }

  i2s_zero_dma_buffer(I2S_PORT);
  i2s_start(I2S_PORT);

  i2sRunning = true;
}


static void i2sEnsureStopped() {

  if (!i2sRunning) {
    return;
  }

  i2s_zero_dma_buffer(I2S_PORT);
  i2s_stop(I2S_PORT);

  i2sRunning = false;
}


// Escribe muestras mono duplicandolas a L/R.
// Bloquea hasta que el DMA tiene sitio: eso es
// exactamente el backpressure que queremos.
static void playMono(const int16_t *mono, size_t sampleCount) {

  for (size_t i = 0; i < sampleCount; i++) {

    stereoBuffer[i * 2]     = mono[i];
    stereoBuffer[i * 2 + 1] = mono[i];
  }

  size_t bytesWritten = 0;

  i2s_write(
    I2S_PORT,
    stereoBuffer,
    sampleCount * 2 * sizeof(int16_t),
    &bytesWritten,
    portMAX_DELAY
  );
}


static void playSilence(size_t sampleCount) {

  memset(stereoBuffer, 0, sizeof(stereoBuffer));

  size_t remaining = sampleCount;

  while (remaining > 0) {

    size_t block = remaining > (MAX_PAYLOAD / 2)
      ? (MAX_PAYLOAD / 2)
      : remaining;

    size_t bytesWritten = 0;

    i2s_write(
      I2S_PORT,
      stereoBuffer,
      block * 2 * sizeof(int16_t),
      &bytesWritten,
      portMAX_DELAY
    );

    remaining -= block;
  }
}


// ======================================================
// CAPTURA DEL MICROFONO
// ======================================================

// Lee un bloque, lo convierte a int16 en micPcm y
// devuelve el nivel medio en la escala calibrada.
// Devuelve -1 si no pudo leer un bloque completo.
static int32_t captureBlock() {

  size_t bytesRead = 0;

  esp_err_t result = i2s_read(
    I2S_PORT,
    micRaw,
    sizeof(micRaw),
    &bytesRead,
    portMAX_DELAY
  );

  if (result != ESP_OK) {
    return -1;
  }

  size_t samples = bytesRead / sizeof(int32_t);

  if (samples == 0) {
    return -1;
  }

  uint64_t levelSum = 0;

  for (size_t i = 0; i < samples; i++) {

    int32_t raw = micRaw[i];

    // Nivel en la escala con la que se calibraron
    // los umbrales de VAD.
    int32_t level = raw >> LEVEL_SHIFT;

    if (level < 0) {
      level = -level;
    }

    levelSum += (uint32_t)level;

    // Muestra con ganancia, recortada a int16.
    int32_t scaled = raw >> MIC_SHIFT;

    if (scaled >  32767) scaled =  32767;
    if (scaled < -32768) scaled = -32768;

    micPcm[i] = (int16_t)scaled;

    int32_t magnitude = scaled < 0 ? -scaled : scaled;

    if ((uint16_t)magnitude > phrasePeak) {
      phrasePeak = (uint16_t)magnitude;
    }
  }

  // Rellenar si el bloque vino corto.
  for (size_t i = samples; i < MIC_BLOCK_SAMPLES; i++) {
    micPcm[i] = 0;
  }

  return (int32_t)(levelSum / samples);
}


static void pushPreRoll() {

  memcpy(
    preRoll[preRollHead],
    micPcm,
    sizeof(micPcm)
  );

  preRollHead = (uint8_t)((preRollHead + 1) % PREROLL_BLOCKS);

  if (preRollCount < PREROLL_BLOCKS) {
    preRollCount++;
  }
}


// Envia el pre-roll en orden cronologico.
static void flushPreRoll() {

  for (uint8_t i = 0; i < preRollCount; i++) {

    uint8_t index = (uint8_t)(
      (preRollHead + PREROLL_BLOCKS - preRollCount + i) % PREROLL_BLOCKS
    );

    sendUpFrame(
      UP_AUDIO,
      (const uint8_t *)preRoll[index],
      (uint16_t)sizeof(micPcm)
    );
  }

  preRollCount = 0;
  preRollHead  = 0;
}


static void finishPhrase() {

  uint8_t peakBytes[2];

  peakBytes[0] = (uint8_t)(phrasePeak & 0xFF);
  peakBytes[1] = (uint8_t)((phrasePeak >> 8) & 0xFF);

  // El pico viaja en el END para poder ajustar MIC_SHIFT
  // con una medida real en vez de a ojo.
  sendUpFrame(UP_END, peakBytes, 2);

  Serial.flush();

  resetVad();
}


static int32_t voiceThreshold() {

  if (noiseFloor < 0) {
    return VOICE_FLOOR_MIN;
  }

  int32_t threshold =
    (noiseFloor * VOICE_FACTOR_NUM) / VOICE_FACTOR_DEN;

  return threshold < VOICE_FLOOR_MIN ? VOICE_FLOOR_MIN : threshold;
}


static int32_t silenceThreshold() {

  if (noiseFloor < 0) {
    return SILENCE_FLOOR_MIN;
  }

  int32_t threshold =
    (noiseFloor * SILENCE_FACTOR_NUM) / SILENCE_FACTOR_DEN;

  return threshold < SILENCE_FLOOR_MIN ? SILENCE_FLOOR_MIN : threshold;
}


static void reportLevel(int32_t level) {

  if (levelCountdown > 0) {
    levelCountdown--;
    return;
  }

  levelCountdown = LEVEL_REPORT_BLOCKS;

  uint16_t levelOut = level > 65535 ? 65535 : (uint16_t)level;
  uint16_t noiseOut = noiseFloor < 0
    ? 0
    : (noiseFloor > 65535 ? 65535 : (uint16_t)noiseFloor);

  uint8_t body[4];

  body[0] = (uint8_t)(levelOut & 0xFF);
  body[1] = (uint8_t)((levelOut >> 8) & 0xFF);
  body[2] = (uint8_t)(noiseOut & 0xFF);
  body[3] = (uint8_t)((noiseOut >> 8) & 0xFF);

  sendUpFrame(UP_LEVEL, body, 4);
}


static void serviceMicrophone() {

  int32_t level = captureBlock();

  if (level < 0) {
    return;
  }

  reportLevel(level);

  if (!recording) {

    // El ruido de fondo se mide SOLO cuando no hay voz, y con
    // una media movil lenta, para que la propia voz no lo
    // arrastre hacia arriba y suba los umbrales con ella.
    if (noiseFloor < 0) {
      noiseFloor = level;
    } else if (level < voiceThreshold()) {
      noiseFloor +=
        (level - noiseFloor) >> NOISE_EMA_SHIFT;
    }

    pushPreRoll();

    if (level > voiceThreshold()) {

      voiceBlocks++;

      if (voiceBlocks >= VOICE_BLOCKS_TO_START) {

        recording     = true;
        silenceBlocks = 0;
        phraseBlocks  = 0;

        sendUpFrame(UP_START, NULL, 0);

        // El pre-roll ya contiene el arranque de la
        // palabra, incluido el bloque actual.
        flushPreRoll();
      }

    } else {

      voiceBlocks = 0;
    }

    return;
  }


  // Ya grabando.
  sendUpFrame(
    UP_AUDIO,
    (const uint8_t *)micPcm,
    (uint16_t)sizeof(micPcm)
  );

  phraseBlocks++;

  // Histeresis: ya hablando, el umbral para dar por
  // terminada la frase es MAS BAJO que el de inicio.
  if (level < silenceThreshold()) {

    silenceBlocks++;

    if (silenceBlocks >= SILENCE_BLOCKS_TO_STOP) {
      finishPhrase();
      return;
    }

  } else {

    silenceBlocks = 0;
  }

  if (phraseBlocks >= MAX_PHRASE_BLOCKS) {
    finishPhrase();
  }
}


// ======================================================
// COMANDOS
// ======================================================

static void handleBegin(uint8_t seq, const uint8_t *payload, uint16_t length) {

  if (length != 4) {
    sendToken(TOK_ERR);
    return;
  }

  expectedBytes =
      ((uint32_t)payload[0])
    | ((uint32_t)payload[1] << 8)
    | ((uint32_t)payload[2] << 16)
    | ((uint32_t)payload[3] << 24);

  receivedBytes = 0;
  haveLastSeq   = false;

  // Cambio a modo habla. Si la captura estaba a medias,
  // se descarta: Kira no se escucha a si misma.
  resetVad();

  if (!i2sInstallSpeak()) {

    sendToken(TOK_ERR);

    // El puente descarta el texto que no encaja con sus
    // parsers, asi que decir POR QUE fallo no rompe nada y
    // ahorra adivinar.
    Serial.printf("KIRA ERR_SPEAK i2s=%d\n", (int)lastI2sError);

    // Volver a un estado conocido en vez de quedarse sin driver.
    i2sInstallListen();

    return;
  }

  sessionActive = true;

  i2sEnsureStarted();

  sendAck(seq);
}


static void handleData(uint8_t seq, const uint8_t *payload, uint16_t length) {

  if (!sessionActive) {
    sendToken(TOK_ERR);
    return;
  }

  // Reenvio: el ACK anterior se perdio. Confirmar
  // otra vez SIN reproducir de nuevo.
  if (haveLastSeq && seq == lastSeq) {
    sendAck(seq);
    return;
  }

  if (length == 0 || (length % 2) != 0) {
    sendToken(TOK_ERR);
    return;
  }

  playMono((const int16_t *)payload, length / 2);

  receivedBytes += length;

  lastSeq     = seq;
  haveLastSeq = true;

  sendAck(seq);
}


static void handleEnd(uint8_t seq) {

  if (!sessionActive) {
    sendToken(TOK_ERR);
    return;
  }

  // Empujar silencio: i2s_write bloquea hasta que el
  // audio real ya salio por el parlante. Solo entonces
  // DONE es verdad.
  playSilence(TAIL_SILENCE_SAMPLES);

  i2sEnsureStopped();

  sessionActive = false;
  haveLastSeq   = false;

  sendToken(TOK_DONE);

  // Volver a escuchar. Kira queda lista para la
  // siguiente frase sin reiniciar.
  i2sInstallListen();
  resetVad();
}


static void handleAbort(uint8_t seq) {

  i2sEnsureStopped();

  sessionActive = false;
  haveLastSeq   = false;
  receivedBytes = 0;
  expectedBytes = 0;

  sendAck(seq);

  i2sInstallListen();
  resetVad();
}


// ======================================================
// LECTURA DE UN FRAME
// ======================================================
//
// Frame PC -> ESP32:
//
//   0xA5 0x5A  CMD  SEQ  LEN_LO LEN_HI  payload[LEN]  CK_LO CK_HI
//
// CK = suma de 16 bits de CMD + SEQ + LEN_LO + LEN_HI
//      + todos los bytes de payload.
//
// Cualquier byte que no encaje se descarta: la basura
// del bootloader no puede confundir al parser.
//
static void processFrame() {

  uint8_t cmd;
  uint8_t seq;
  uint8_t lengthBytes[2];

  if (!readByteTimeout(cmd, FRAME_TIMEOUT_MS))  { sendToken(TOK_NAK); return; }
  if (!readByteTimeout(seq, FRAME_TIMEOUT_MS))  { sendToken(TOK_NAK); return; }

  if (!readExactTimeout(lengthBytes, 2, FRAME_TIMEOUT_MS)) {
    sendToken(TOK_NAK);
    return;
  }

  uint16_t length =
      ((uint16_t)lengthBytes[0])
    | ((uint16_t)lengthBytes[1] << 8);

  if (length > MAX_PAYLOAD) {
    sendToken(TOK_NAK);
    return;
  }

  if (length > 0) {

    if (!readExactTimeout(payloadBuffer, length, FRAME_TIMEOUT_MS)) {
      sendToken(TOK_NAK);
      return;
    }
  }

  uint8_t checksumBytes[2];

  if (!readExactTimeout(checksumBytes, 2, FRAME_TIMEOUT_MS)) {
    sendToken(TOK_NAK);
    return;
  }

  uint16_t expectedChecksum =
      ((uint16_t)checksumBytes[0])
    | ((uint16_t)checksumBytes[1] << 8);

  uint16_t checksum = 0;

  checksum += cmd;
  checksum += seq;
  checksum += lengthBytes[0];
  checksum += lengthBytes[1];

  for (uint16_t i = 0; i < length; i++) {
    checksum += payloadBuffer[i];
  }

  if (checksum != expectedChecksum) {
    // La PC reenvia el mismo SEQ; nada se reproduce.
    sendToken(TOK_NAK);
    return;
  }


  switch (cmd) {

    case CMD_PING:
      sendToken(TOK_READY);
      break;

    case CMD_BEGIN:
      handleBegin(seq, payloadBuffer, length);
      break;

    case CMD_DATA:
      handleData(seq, payloadBuffer, length);
      break;

    case CMD_END:
      handleEnd(seq);
      break;

    case CMD_ABORT:
      handleAbort(seq);
      break;

    default:
      sendToken(TOK_ERR);
      break;
  }
}


// Consume frames pendientes de la PC. Devuelve true si
// atendio alguno, para no capturar microfono en ese ciclo.
static bool serviceSerial() {

  bool handled = false;

  while (Serial.available() > 0) {

    int value = Serial.read();

    if (value < 0) {
      break;
    }

    if ((uint8_t)value != SYNC0) {
      continue;
    }

    uint8_t second;

    if (!readByteTimeout(second, FRAME_TIMEOUT_MS)) {
      break;
    }

    // 0xA5 0xA5 ... : puede ser el sync real desplazado.
    while (second == SYNC0) {

      if (!readByteTimeout(second, FRAME_TIMEOUT_MS)) {
        return handled;
      }
    }

    if (second != SYNC1) {
      continue;
    }

    processFrame();

    handled = true;

    // Durante una sesion de habla hay que seguir
    // consumiendo frames sin volver al microfono.
    if (!sessionActive) {
      break;
    }
  }

  return handled;
}


// ======================================================
// SETUP
// ======================================================

void setup() {

  // Debe llamarse ANTES de begin().
  Serial.setRxBufferSize(SERIAL_RX_BUFFER);

  Serial.begin(SERIAL_BAUD);
  Serial.setTimeout(FRAME_TIMEOUT_MS);

  resetVad();

  if (!i2sInstallListen()) {
    Serial.println("KIRA ERROR_I2S");
    return;
  }

  // Unico texto que emite el firmware, y solo al arrancar.
  // A partir de aqui todo son tokens de 1-2 bytes o frames.
  Serial.println("KIRA READY");
}


// ======================================================
// LOOP
// ======================================================

void loop() {

  // Los comandos de la PC tienen prioridad: si llega
  // audio para reproducir, se deja de escuchar.
  if (serviceSerial()) {
    return;
  }

  if (audioMode == MODE_LISTEN) {
    serviceMicrophone();
  }
}
