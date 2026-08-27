"""
KIRA — Text To Speech desde la PC hacia el ESP32.

Flujo:

    texto -> pyttsx3 -> WAV -> FFmpeg -> PCM mono 16-bit 16 kHz
          -> serial -> ESP32 -> I2S -> MAX98357A -> parlante

Protocolo (ver seccion 6 de CLAUDE.md):

    PC -> ESP32:  0xA5 0x5A CMD SEQ LEN_LO LEN_HI payload CK_LO CK_HI
    ESP32 -> PC:  tokens de 1 byte (2 bytes para ACK: 0x06 + SEQ)

Cada bloque de audio espera su ACK. El ESP32 contesta el ACK
DESPUES de escribir en I2S, asi que el propio DAC marca el ritmo:
no hay temporizadores adivinados ni desborde del RX serial.

Requiere: pyserial, pyttsx3, FFmpeg en el PATH.
No usa pydub (Python 3.13 ya no trae audioop).
"""

import os
import struct
import subprocess
import sys
import tempfile
import time
import wave

import pyttsx3
import serial


# ======================================================
# CONFIG
# ======================================================

PORT = "COM5"
BAUD = 921600

SAMPLE_RATE = 16000

# 1024 B = 512 muestras = 32 ms de audio por bloque.
# Debe coincidir con MAX_PAYLOAD del firmware.
CHUNK_BYTES = 1024

# Ganancia de software aplicada por FFmpeg.
# 1.0 = sin tocar. Subir solo si se oye demasiado bajo.
VOLUME = 1.0

# Voz de Windows a usar. Se busca esta cadena dentro del id
# de la voz. "ES-ES" = Helena (espanol de Espana).
# Sin esto, Windows usa Zira (ingles) y "Hola, soy Kira"
# sale con acento ingles.
VOICE_MATCH = "ES-"

# Palabras por minuto. La voz por defecto de SAPI5 va rapida.
VOICE_RATE = 165

# Texto a reproducir.
text = "Hola, soy Kira."


# ======================================================
# PROTOCOLO
# ======================================================

SYNC = b"\xA5\x5A"

CMD_PING = 0x01
CMD_BEGIN = 0x02
CMD_DATA = 0x03
CMD_END = 0x04
CMD_ABORT = 0x05

TOK_ACK = 0x06
TOK_NAK = 0x15
TOK_READY = 0x21
TOK_DONE = 0x22
TOK_ERR = 0x23

TOKEN_NAMES = {
    TOK_ACK: "ACK",
    TOK_NAK: "NAK",
    TOK_READY: "READY",
    TOK_DONE: "DONE",
    TOK_ERR: "ERR",
}


def build_frame(cmd, seq, payload=b""):

    length = len(payload)

    header = struct.pack("<BBH", cmd, seq, length)

    checksum = (cmd + seq + (length & 0xFF) + (length >> 8) + sum(payload)) & 0xFFFF

    return SYNC + header + payload + struct.pack("<H", checksum)


# ======================================================
# TTS
# ======================================================

def create_tts_wav(text):

    print("Generando voz...")

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = handle.name
    handle.close()

    engine = pyttsx3.init()

    for voice in engine.getProperty("voices"):

        if VOICE_MATCH.upper() in voice.id.upper():
            engine.setProperty("voice", voice.id)
            print("Voz:", voice.name)
            break

    else:
        print("Aviso: no encontre voz con", VOICE_MATCH, "- usando la de por defecto.")

    engine.setProperty("rate", VOICE_RATE)

    engine.save_to_file(text, path)
    engine.runAndWait()
    engine.stop()

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("pyttsx3 no genero audio.")

    return path


# ======================================================
# FFMPEG
# ======================================================

def convert_audio(input_path):

    print("Convirtiendo a PCM mono 16-bit 16 kHz...")

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    output_path = handle.name
    handle.close()

    command = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ac", "1",                  # mono
        "-ar", str(SAMPLE_RATE),     # 16 kHz
        "-acodec", "pcm_s16le",      # PCM signed 16-bit little endian
    ]

    if VOLUME != 1.0:
        command += ["-af", f"volume={VOLUME}"]

    command += [output_path]

    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        print("ERROR FFMPEG:")
        print(result.stderr)
        raise RuntimeError("FFmpeg no pudo convertir el audio.")

    return output_path


def load_pcm(path):

    with wave.open(path, "rb") as wav:

        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()

        print()
        print("Formato final:")
        print("  Canales:", channels)
        print("  Bits:", width * 8)
        print("  Sample rate:", rate)
        print(f"  Duracion: {frames / rate:.2f} s")
        print()

        if channels != 1:
            raise ValueError("El audio no quedo mono.")

        if width != 2:
            raise ValueError("El audio no quedo PCM 16-bit.")

        if rate != SAMPLE_RATE:
            raise ValueError(f"El audio no quedo en {SAMPLE_RATE} Hz.")

        return wav.readframes(frames)


# ======================================================
# SERIAL
# ======================================================

def open_port():
    """
    Abre el puerto controlando DTR/RTS a mano.

    En las placas con CH340, RTS va al pin EN y DTR a GPIO0.
    Abrir el puerto sin cuidado resetea el ESP32 en un momento
    indeterminado, que es lo que rompia los intentos anteriores.
    Aqui el reset se provoca a proposito para partir siempre
    del mismo estado conocido.
    """

    print(f"Abriendo {PORT} a {BAUD} baud...")

    ser = serial.Serial()
    ser.port = PORT
    ser.baudrate = BAUD
    ser.timeout = 0.2
    ser.write_timeout = 5
    ser.dtr = False
    ser.rts = False

    ser.open()

    # Reset deliberado: EN a masa y sueltar. GPIO0 se queda
    # alto, asi que arranca en modo normal, no en bootloader.
    ser.dtr = False
    ser.rts = True
    time.sleep(0.12)
    ser.rts = False

    # El boot ROM escupe su banner a 115200: leido a 921600
    # son bytes basura y ceros. Se descarta todo.
    print("Esperando arranque del ESP32...")
    time.sleep(1.2)

    ser.reset_input_buffer()
    ser.reset_output_buffer()

    return ser


def read_token(ser, timeout):
    """
    Devuelve el siguiente token de 1 byte del ESP32, o None.
    Los bytes que no son tokens conocidos (basura de arranque,
    banner de texto) se descartan sin romper nada.
    """

    deadline = time.time() + timeout

    while time.time() < deadline:

        data = ser.read(1)

        if not data:
            continue

        token = data[0]

        if token in TOKEN_NAMES:
            return token

    return None


def wait_ready(ser, attempts=25):
    """
    No depende de capturar un READY emitido una sola vez:
    la PC pregunta con PING hasta que el ESP32 contesta.
    """

    print("Buscando ESP32...")

    frame = build_frame(CMD_PING, 0)

    for attempt in range(attempts):

        ser.reset_input_buffer()
        ser.write(frame)
        ser.flush()

        token = read_token(ser, 0.25)

        if token == TOK_READY:
            return True

    return False


def send_frame_acked(ser, cmd, seq, payload=b"", timeout=3.0, retries=3):
    """
    Envia un frame y espera su ACK con el mismo SEQ.
    Si el ACK se pierde o llega NAK se reintenta el mismo SEQ;
    el firmware detecta el duplicado y no reproduce dos veces.
    """

    frame = build_frame(cmd, seq, payload)

    for attempt in range(retries):

        ser.write(frame)
        ser.flush()

        deadline = time.time() + timeout

        while time.time() < deadline:

            token = read_token(ser, max(0.0, deadline - time.time()))

            if token is None:
                break

            if token == TOK_ACK:

                echo = ser.read(1)

                if echo and echo[0] == seq:
                    return True

                # ACK de otro bloque (duplicado tardio): seguir esperando.
                continue

            if token == TOK_NAK:
                break

            if token == TOK_ERR:
                raise RuntimeError(
                    f"El ESP32 rechazo el comando 0x{cmd:02X} (ERR)."
                )

        # Reintento: limpiar restos antes de repetir.
        ser.reset_input_buffer()

    return False


def send_pcm(ser, pcm):

    total = len(pcm)

    if not send_frame_acked(ser, CMD_BEGIN, 0, struct.pack("<I", total)):
        raise RuntimeError("El ESP32 no confirmo el inicio (BEGIN).")

    print("Enviando audio...")
    print("Reproduciendo...")

    seq = 1
    sent = 0

    for offset in range(0, total, CHUNK_BYTES):

        chunk = pcm[offset:offset + CHUNK_BYTES]

        if not send_frame_acked(ser, CMD_DATA, seq, chunk):
            raise RuntimeError(
                f"Sin ACK en el bloque {seq} "
                f"({sent}/{total} bytes enviados)."
            )

        sent += len(chunk)
        seq = (seq + 1) & 0xFF

        if seq == 0:
            seq = 1

    # END: el firmware empuja silencio y solo contesta DONE
    # cuando la cola de audio ya salio por el parlante.
    frame = build_frame(CMD_END, 0)

    ser.write(frame)
    ser.flush()

    token = read_token(ser, 10.0)

    if token != TOK_DONE:
        raise RuntimeError(
            "El ESP32 no confirmo el fin de reproduccion (DONE). "
            f"Ultimo token: {TOKEN_NAMES.get(token, token)}"
        )

    print("Reproduccion completada")


# ======================================================
# MAIN
# ======================================================

def main():

    raw_path = None
    pcm_path = None
    ser = None

    try:

        raw_path = create_tts_wav(text)
        pcm_path = convert_audio(raw_path)
        pcm = load_pcm(pcm_path)

        ser = open_port()

        if not wait_ready(ser):
            raise RuntimeError(
                "El ESP32 no respondio al PING. "
                "Revisar puerto, baud y que el firmware este subido."
            )

        print("ESP32 listo")

        send_pcm(ser, pcm)

        return 0

    except Exception as error:

        print()
        print("FALLO:", error)

        # Dejar el firmware en reposo si quedo a medias.
        if ser is not None and ser.is_open:
            try:
                ser.write(build_frame(CMD_ABORT, 0))
                ser.flush()
            except Exception:
                pass

        return 1

    finally:

        if ser is not None and ser.is_open:
            ser.close()
            print("Puerto cerrado")

        for path in (raw_path, pcm_path):
            if path and os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    sys.exit(main())
