// ======================================================
// KIRA — Firmware de SALIDA de audio (I2S TX)
//
// Recibe PCM mono 16-bit 16 kHz por serial desde la PC
// y lo reproduce por el MAX98357A + parlante.
//
// Protocolo: ver seccion 6 de CLAUDE.md.
// Framing con sync + checksum + numero de secuencia,
// y ACK por bloque (backpressure real: el ACK se envia
// DESPUES de i2s_write, asi el DAC marca el ritmo).
//
// Cableado (NO modificar):
//   BCLK -> GPIO 26   (compartido con SCK del INMP441)
//   LRC  -> GPIO 25   (compartido con WS  del INMP441)
//   DIN  -> GPIO 27   (exclusivo de salida)
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
// PROTOCOLO
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
// ESTADO
// ======================================================

// Buffers globales: no en la pila, para no arriesgar
// desbordarla dentro del loop.
static uint8_t payloadBuffer[MAX_PAYLOAD];
static int16_t stereoBuffer[MAX_PAYLOAD];   // 512 muestras -> 1024 int16

static bool     sessionActive   = false;
static bool     i2sRunning      = false;
static uint32_t expectedBytes   = 0;
static uint32_t receivedBytes   = 0;
static uint8_t  lastSeq         = 0;
static bool     haveLastSeq     = false;


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


// ======================================================
// I2S
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
}


static void handleAbort(uint8_t seq) {

  i2sEnsureStopped();

  sessionActive = false;
  haveLastSeq   = false;
  receivedBytes = 0;
  expectedBytes = 0;

  sendAck(seq);
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


// ======================================================
// SETUP
// ======================================================

void setup() {

  // Debe llamarse ANTES de begin().
  Serial.setRxBufferSize(SERIAL_RX_BUFFER);

  Serial.begin(SERIAL_BAUD);
  Serial.setTimeout(FRAME_TIMEOUT_MS);


  i2s_config_t i2s_config = {

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


  i2s_pin_config_t pin_config = {

    .bck_io_num   = I2S_BCLK,
    .ws_io_num    = I2S_LRC,
    .data_out_num = I2S_DOUT,
    .data_in_num  = I2S_PIN_NO_CHANGE
  };


  if (i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL) != ESP_OK) {
    Serial.println("KIRA-TTS ERROR_I2S");
    return;
  }

  if (i2s_set_pin(I2S_PORT, &pin_config) != ESP_OK) {
    Serial.println("KIRA-TTS ERROR_PIN");
    return;
  }

  i2s_zero_dma_buffer(I2S_PORT);

  // En reposo el TX queda parado: sin siseo en el parlante.
  i2s_stop(I2S_PORT);
  i2sRunning = false;

  // Unico texto que emite el firmware, y solo al arrancar.
  // A partir de aqui todo son tokens de 1 o 2 bytes.
  Serial.println("KIRA-TTS READY");
}


// ======================================================
// LOOP
// ======================================================

void loop() {

  int value = Serial.read();

  if (value < 0) {
    return;
  }

  if ((uint8_t)value != SYNC0) {
    return;
  }

  uint8_t second;

  if (!readByteTimeout(second, FRAME_TIMEOUT_MS)) {
    return;
  }

  // 0xA5 0xA5 ... : puede ser el sync real desplazado.
  while (second == SYNC0) {

    if (!readByteTimeout(second, FRAME_TIMEOUT_MS)) {
      return;
    }
  }

  if (second != SYNC1) {
    return;
  }

  processFrame();
}