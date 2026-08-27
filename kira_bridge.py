"""
KIRA — Puente entre el ESP32 y el orquestador de agentes (eve).

UN SOLO PROCESO, dueno del puerto serie de principio a fin. Dos procesos no
pueden compartir el puerto COM, asi que todo el ciclo vive aqui.

Ciclo:

    INMP441 -> ESP32 -> frames "AA 55" -> faster-whisper (STT local)
      -> wake word "Oye Kira" -> POST a eve -> agente raiz
      -> subagente -> texto -> SAPI5 + FFmpeg -> PCM 16 kHz
      -> protocolo v2 -> ESP32 -> MAX98357A -> parlante

Protocolos: ver seccion 6 de CLAUDE.md.

    ESP32 -> PC:  0xAA 0x55 TIPO LEN_LO LEN_HI payload        (audio del mic)
    PC -> ESP32:  0xA5 0x5A CMD SEQ LEN_LO LEN_HI payload CK  (audio a reproducir)
    ESP32 -> PC:  tokens de 1 byte (2 para ACK: 0x06 + SEQ)

Requiere: pyserial, comtypes, faster-whisper, FFmpeg en el PATH, y el
servidor de eve corriendo.

No usa pydub: Python 3.13 elimino audioop.
No usa pyttsx3: su driver SAPI5 se cuelga en el segundo runAndWait() del
mismo proceso, y este script habla en bucle.
"""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

import serial
import serial.tools.list_ports

from comtypes.client import CreateObject
from comtypes.gen import SpeechLib

from faster_whisper import WhisperModel


# ======================================================
# CONFIG
# ======================================================

# Puerto serie. None = autodetectar (busca el CH340 de esta placa).
# CLAUDE.md avisa: NO asumir que COM5 sera siempre el puerto.
PORT = os.environ.get("KIRA_PORT") or None
PORT_FALLBACK = "COM5"

BAUD = 921600

SAMPLE_RATE = 16000

# 1024 B = 512 muestras = 32 ms por bloque.
# Debe coincidir con MAX_PAYLOAD del firmware.
CHUNK_BYTES = 1024

# Servidor de eve. `eve dev` escucha en 2000; en produccion `eve start`
# usa el puerto que se le pase por PORT.
EVE_URL = os.environ.get("KIRA_EVE_URL", "http://127.0.0.1:2000")

# Ruta del .env.local del agente. Es la UNICA copia del token: el puente lo
# lee de ahi en vez de tener el secreto duplicado en dos sitios.
EVE_ENV_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "brain",
    ".env.local",
)

# Reusar la misma sesion de eve entre frases da memoria de
# conversacion gratis: eve la mantiene durable del lado servidor.
REUSE_SESSION = True

# Whisper local. Gratis, sin red, sin coste por uso.
WHISPER_MODEL = "small"

# Voz de Windows. "ES-" = Helena (espanol de Espana). Sin esto
# Windows usa Zira (ingles) y todo sale con acento ingles.
VOICE_MATCH = "ES-"

# Velocidad en la escala de SAPI (-10 a 10). 0 es exactamente
# la velocidad que pyttsx3 producia con rate=165, que es la que
# quedo validada: su formula da int(log(165/156.63, 1.11)) == 0.
VOICE_RATE = 0

# Cadena de FFmpeg para subir el volumen de la voz.
#
# La voz de SAPI sale a unos -22.4 dBFS de RMS, que en un parlante de 40 mm
# se oye bajita. Medido sobre la misma frase:
#
#   sin filtro                        RMS -22.4 dBFS    0 recortadas
#   volume=2.0 solo                   RMS -16.5 dBFS   54 recortadas
#   acompressor 4:1                   RMS -19.6 dBFS    0   (PEOR)
#   acompressor 8:1                   RMS -21.1 dBFS    0   (PEOR)
#   speechnorm + limiter              RMS -16.6 dBFS    0 recortadas
#   highpass150 + sn + vol2.0 + lim   RMS -13.8 dBFS   17 recortadas  <- esta
#   highpass250 + sn + vol6.0 + lim   RMS -12.0 dBFS   49 recortadas
#
# Conclusiones, para no repetir el camino:
#   - acompressor EMPEORA el volumen percibido, en cualquier ratio.
#   - el limitador ya topa: subir la entrada de 2.0 a 6.0 solo da +2 dB y
#     duplica el recorte. El RMS se asintota en unos -12 dBFS.
#   - highpass a 150 Hz mejora RMS y recorte a la vez, y evita que el
#     parlante gaste excursion en graves que no puede reproducir.
#
# Acumulado: +8.6 dB sobre la voz cruda. Queda menos de 2 dB por exprimir.
# Si hay que subir volumen otra vez, mirar primero lo ACUSTICO: montar el
# parlante en la carcasa dio mas que todo este filtro junto.
LOUDNESS_FILTER = (
    "highpass=f=150"
    ",speechnorm=e=25:r=0.0001:l=1"
    ",volume=2.0"
    ",alimiter=limit=0.97"
)

# Ganancia extra encima de la cadena anterior. 1.0 = sin tocar.
VOLUME = 1.0

# Audio mas corto que esto no se transcribe: es un ruido, no una frase.
MIN_AUDIO_BYTES = 2000

# Mostrar la telemetria de nivel del microfono. Util para
# calibrar MIC_SHIFT y ver los umbrales adaptativos en vivo.
# Poner en False cuando ya no haga falta el ruido en pantalla.
SHOW_LEVELS = os.environ.get("KIRA_SHOW_LEVELS", "1") != "0"


# ======================================================
# PROTOCOLO PC -> ESP32 (v2)
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


# ======================================================
# PROTOCOLO ESP32 -> PC (audio del microfono)
# ======================================================

UP_MAGIC0 = 0xAA
UP_MAGIC1 = 0x55

UP_START = 1
UP_AUDIO = 2
UP_END = 3
UP_LEVEL = 4


# Texto suelto que emite el ESP32 (banner de arranque,
# diagnosticos como "KIRA ERR_SPEAK i2s=-1"). Los parsers lo
# descartan por diseno, asi que se acumula aparte para poder
# mostrarlo en vez de perderlo.
_esp_text = bytearray()


def collect_esp_text(byte_value):

    global _esp_text

    if byte_value == 0x0A:  # newline

        line = _esp_text.decode("ascii", errors="replace").strip()
        _esp_text = bytearray()

        if line:
            print(f"  [ESP32] {line}")

        return

    if 0x20 <= byte_value <= 0x7E:

        _esp_text.append(byte_value)

        # Nunca crecer sin limite con basura binaria.
        if len(_esp_text) > 200:
            _esp_text = bytearray()

    else:
        _esp_text = bytearray()


def build_frame(cmd, seq, payload=b""):

    length = len(payload)

    header = struct.pack("<BBH", cmd, seq, length)

    checksum = (cmd + seq + (length & 0xFF) + (length >> 8) + sum(payload)) & 0xFFFF

    return SYNC + header + payload + struct.pack("<H", checksum)


# ======================================================
# SERIAL
# ======================================================

def find_port():
    """
    Busca la placa por su descripcion. El CH340 aparece en
    Windows como "USB-SERIAL CH340". Si no lo encuentra, cae
    al puerto de reserva.
    """

    if PORT:
        return PORT

    for candidate in serial.tools.list_ports.comports():

        haystack = f"{candidate.description} {candidate.manufacturer}".upper()

        if "CH340" in haystack or "USB-SERIAL" in haystack:
            print(f"Placa detectada en {candidate.device} ({candidate.description})")
            return candidate.device

    print(f"Aviso: no detecte el CH340. Probando {PORT_FALLBACK}.")

    return PORT_FALLBACK


def open_port(port):
    """
    Abre el puerto controlando DTR/RTS a mano.

    En las placas con CH340, RTS va al pin EN y DTR a GPIO0.
    Abrir el puerto sin cuidado resetea el ESP32 en un momento
    indeterminado. Aqui el reset se provoca a proposito para
    partir siempre del mismo estado conocido.
    """

    print(f"Abriendo {port} a {BAUD} baud...")

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.timeout = 0.2
    ser.write_timeout = 5
    ser.dtr = False
    ser.rts = False

    ser.open()

    # Reset deliberado: EN a masa y soltar. GPIO0 se queda alto,
    # asi que arranca en modo normal, no en bootloader.
    ser.dtr = False
    ser.rts = True
    time.sleep(0.12)
    ser.rts = False

    # El boot ROM escupe su banner a 115200: leido a 921600 son
    # bytes basura y ceros. Se descarta todo.
    print("Esperando arranque del ESP32...")
    time.sleep(1.2)

    ser.reset_input_buffer()
    ser.reset_output_buffer()

    return ser


def read_exactly(ser, count, timeout=5.0):

    data = bytearray()
    deadline = time.time() + timeout

    while len(data) < count:

        if time.time() > deadline:
            return None

        chunk = ser.read(count - len(data))

        if chunk:
            data.extend(chunk)

    return bytes(data)


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

        # Frame de audio del microfono todavia en vuelo: consumirlo
        # ENTERO y descartarlo.
        #
        # Sin esto sus bytes se interpretan uno a uno como tokens, y
        # el PCM crudo contiene los cinco valores de token: medido
        # sobre audio real, 0x06 (ACK) aparece 1 cada 107 bytes y
        # 0x23 (ERR) 1 cada 575. De ahi salia el falso "El ESP32
        # rechazo el comando 0x02 (ERR)" (2026-08-27).
        if token == UP_MAGIC0:

            second = ser.read(1)

            if second and second[0] == UP_MAGIC1:

                header = read_exactly(ser, 3, timeout=0.5)

                if header is not None:

                    length = struct.unpack("<H", header[1:3])[0]

                    if 0 < length <= 4096:
                        read_exactly(ser, length, timeout=1.0)

                continue

            if second and second[0] in TOKEN_NAMES:
                return second[0]

            continue

        if token in TOKEN_NAMES:
            return token

        # Aqui es donde aparecen los diagnosticos del firmware,
        # p.ej. "KIRA ERR_SPEAK i2s=-1" tras un ERR.
        collect_esp_text(token)

    return None


def wait_ready(ser, attempts=25):
    """
    No depende de capturar un READY emitido una sola vez:
    la PC pregunta con PING hasta que el ESP32 contesta.
    """

    print("Buscando ESP32...")

    frame = build_frame(CMD_PING, 0)

    for _ in range(attempts):

        ser.reset_input_buffer()
        ser.write(frame)
        ser.flush()

        token = read_token(ser, 0.25)

        if token == TOK_READY:
            return True

    return False


def read_up_frame(ser):
    """
    Lee un frame de subida (audio del microfono).
    Devuelve (tipo, payload) o None si no llego nada.

    Descarta cualquier byte que no encaje con el magic, asi
    que el banner "KIRA READY" y la basura del arranque no
    pueden confundir al parser.
    """

    first = ser.read(1)

    if not first:
        return None

    if first[0] != UP_MAGIC0:
        collect_esp_text(first[0])
        return None

    second = ser.read(1)

    if not second:
        return None

    if second[0] != UP_MAGIC1:
        collect_esp_text(second[0])
        return None

    header = read_exactly(ser, 3, timeout=1.0)

    if header is None:
        return None

    frame_type = header[0]
    length = struct.unpack("<H", header[1:3])[0]

    payload = b""

    if length > 0:

        payload = read_exactly(ser, length, timeout=2.0)

        if payload is None:
            return None

    return frame_type, payload


def send_frame_acked(ser, cmd, seq, payload=b"", timeout=3.0, retries=3):
    """
    Envia un frame y espera su ACK con el mismo SEQ.
    Si el ACK se pierde o llega NAK se reintenta el mismo SEQ;
    el firmware detecta el duplicado y no reproduce dos veces.
    """

    frame = build_frame(cmd, seq, payload)

    for _ in range(retries):

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

                # El firmware manda el motivo como texto JUSTO
                # DESPUES del token (p.ej. "KIRA ERR_SPEAK i2s=-1").
                # Sin este drenado se lanzaba la excepcion antes de
                # leerlo y el diagnostico se perdia, que es lo que
                # paso en la prueba del 2026-08-27.
                deadline_text = time.time() + 0.4

                while time.time() < deadline_text:

                    extra = ser.read(1)

                    if extra:
                        collect_esp_text(extra[0])

                raise RuntimeError(
                    f"El ESP32 rechazo el comando 0x{cmd:02X} (ERR)."
                )

        # Reintento: limpiar restos antes de repetir.
        ser.reset_input_buffer()

    return False


def send_pcm(ser, pcm):

    total = len(pcm)

    # CRITICO: tirar el backlog de entrada antes de hablar.
    #
    # Mientras la PC transcribe, consulta a eve y genera el TTS
    # pasan segundos, y el ESP32 sigue enviando audio del microfono
    # a 32 kB/s si detecta voz. Ese backlog es PCM crudo, y
    # read_token() devuelve el primer byte que coincida con un
    # token conocido: entre miles de bytes aleatorios aparece 0x23,
    # que es TOK_ERR. Resultado: "El ESP32 rechazo el comando 0x02
    # (ERR)" sin que el ESP32 hubiera rechazado nada.
    #
    # Encajaba con los sintomas: intermitente, siempre tras las
    # respuestas mas largas (mas tiempo pensando = mas backlog), y
    # sin el texto de diagnostico que el firmware si emite cuando
    # el error es real (2026-08-27).
    #
    # Descartarlo es lo correcto ademas por comportamiento: lo que
    # se dijo mientras Kira pensaba no es una peticion nueva.
    ser.reset_input_buffer()

    # BEGIN reintentado, como red de seguridad para un fallo real
    # del cambio de modo: si i2sInstallSpeak falla, el firmware
    # contesta ERR y se recupera solo volviendo a ESCUCHA.
    begin_payload = struct.pack("<I", total)

    for attempt in (1, 2, 3):

        try:

            if send_frame_acked(ser, CMD_BEGIN, 0, begin_payload):
                break

            raise RuntimeError("El ESP32 no confirmo el inicio (BEGIN).")

        except RuntimeError as error:

            if attempt == 3:
                raise

            print(f"  BEGIN falló (intento {attempt}): {error} — reintentando")

            ser.reset_input_buffer()
            time.sleep(0.35)

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
    ser.write(build_frame(CMD_END, 0))
    ser.flush()

    token = read_token(ser, 15.0)

    if token != TOK_DONE:
        raise RuntimeError(
            "El ESP32 no confirmo el fin de reproduccion (DONE). "
            f"Ultimo token: {TOKEN_NAMES.get(token, token)}"
        )

    print("Listo.")


# ======================================================
# STT
# ======================================================

def trim_trailing_silence(audio, keep_ms=300):
    """
    Quita el silencio del final, dejando un margen corto.

    El firmware cierra la frase tras SILENCE_STOP_MS de silencio,
    y ese silencio queda dentro de la grabacion. Con 3 s de pausa
    son 3 s que Whisper procesaria para nada, sumando latencia.

    El umbral se saca del propio audio (una fraccion del pico), asi
    que no hay que recalibrarlo si cambia MIC_SHIFT o el volumen
    de la voz.
    """

    block = SAMPLE_RATE * 32 // 1000          # 32 ms, como el firmware
    total = len(audio) // 2

    if total <= block:
        return audio

    samples = struct.unpack(f"<{total}h", audio)

    peak = max(max(samples), -min(samples))

    if peak == 0:
        return audio

    threshold = max(peak // 12, 200)

    keep_blocks = max(1, (keep_ms * SAMPLE_RATE // 1000) // block)

    last_loud = -1

    for index in range(total // block):

        chunk = samples[index * block:(index + 1) * block]

        level = sum(abs(value) for value in chunk) // block

        if level > threshold:
            last_loud = index

    if last_loud < 0:
        return audio

    end_block = min(total // block, last_loud + 1 + keep_blocks)

    return audio[:end_block * block * 2]


def transcribe(model, audio):

    if len(audio) < MIN_AUDIO_BYTES:
        return None

    path = None

    try:

        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        path = handle.name
        handle.close()

        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(audio)

        segments, _ = model.transcribe(
            path,
            language="es",
            beam_size=5,
            vad_filter=True,
        )

        return " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

    finally:

        if path and os.path.exists(path):
            os.remove(path)


# ======================================================
# WAKE WORD
# ======================================================

def normalize_text(text):

    normalized = text.lower()

    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u",
    }

    for original, replacement in replacements.items():
        normalized = normalized.replace(original, replacement)

    return normalized


WAKE_PATTERNS = [
    r"\boye kira\b",
    r"\boye, kira\b",
    r"\boie kira\b",
    r"\bhola kira\b",
    r"\bola kira\b",
]


def contains_wake_word(text):

    normalized = normalize_text(text)

    return any(
        re.search(pattern, normalized)
        for pattern in WAKE_PATTERNS
    )


WAKE_STRIP = re.compile(
    r"(oye|oie|hola|ola)[\s,]+kira[\s,.:;!?-]*",
    re.IGNORECASE,
)


def remove_wake_word(text):
    """
    Devuelve lo que viene DESPUES de la wake word.

    Sin anclar al inicio a proposito: en la primera prueba real
    el usuario dijo "Hola hola, oye Kira, conectate..." y una
    version anclada con ^ no recortaba nada, asi que el
    orquestador recibia la wake word dentro de la instruccion.

    Se usa la ULTIMA aparicion: si alguien titubea ("oye Kira...
    oye Kira, apaga la luz"), lo util es lo que sigue al ultimo
    intento. Sobre el texto original, para conservar mayusculas
    y acentos.
    """

    last = None

    for match in WAKE_STRIP.finditer(text):
        last = match

    if last is None:
        return text.strip()

    return text[last.end():].strip()


# ======================================================
# EVE
# ======================================================

def load_agent_token():
    """
    Token compartido con el canal de eve.

    Prioridad: variable de entorno, y si no, `brain/.env.local`. Leerlo del
    mismo archivo que usa eve evita tener el secreto en dos sitios que se
    puedan desincronizar.

    Devuelve None si no hay token. En ese caso el puente sigue funcionando
    contra `eve dev`, que acepta al principal sintetico de `localDev()`, pero
    NO contra `eve start`.
    """

    from_env = os.environ.get("KIRA_AGENT_TOKEN")

    if from_env:
        return from_env.strip()

    if not os.path.exists(EVE_ENV_FILE):
        return None

    try:

        with open(EVE_ENV_FILE, encoding="utf-8") as handle:

            for line in handle:

                line = line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                name, _, value = line.partition("=")

                if name.strip() == "KIRA_AGENT_TOKEN":
                    return value.strip().strip('"').strip("'")

    except OSError:
        return None

    return None


AGENT_TOKEN = load_agent_token()


def eve_headers(extra=None):

    headers = dict(extra or {})

    if AGENT_TOKEN:
        headers["authorization"] = f"Bearer {AGENT_TOKEN}"

    return headers


def eve_health():
    """
    La ruta de salud es publica: eve la deja fuera del walk de auth para que
    los monitores puedan sondearla. Sirve para saber si el proceso esta vivo,
    NO para saber si el token es correcto.
    """

    try:

        request = urllib.request.Request(
            f"{EVE_URL}/eve/v1/health",
            headers=eve_headers(),
        )

        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8")).get("ok") is True

    except Exception:
        return False


def wait_for_eve(timeout=None):
    """
    Espera a que eve responda, en vez de rendirse al primer intento.

    Imprescindible para el arranque automatico: al iniciar sesion las dos
    tareas arrancan a la vez, y el puente casi siempre gana la carrera porque
    eve tiene que levantar su runtime. Sin esta espera, el puente moria en
    cada arranque en frio y Kira quedaba muda hasta que alguien la arrancaba
    a mano.
    """

    if timeout is None:
        timeout = float(os.environ.get("KIRA_EVE_WAIT", "120"))

    deadline = time.time() + timeout
    announced = False

    while True:

        if eve_health():
            return True

        if time.time() >= deadline:
            return False

        if not announced:
            print(f"Esperando a que eve arranque en {EVE_URL}...")
            announced = True

        time.sleep(1.0)


def eve_send(message, session_id=None, event_offset=0):
    """
    Manda el texto al orquestador y devuelve
    (respuesta, session_id, nuevo_offset).

    Dos llamadas: una crea o continua la sesion, la otra lee el
    stream de eventos hasta que el turno termina. El stream es
    NDJSON, un evento JSON por linea.

    OJO con `event_offset`: el stream de una sesion se reproduce
    DESDE EL EVENTO 0, no desde el ultimo. Sin este offset, la
    segunda pregunta leia los eventos del primer turno, cortaba en
    su `session.waiting` y devolvia la respuesta ANTERIOR. En la
    prueba real eso hacia que Kira contestara "Quito" a "cuanto es
    25 por 48" (2026-08-27).

    Doble cinturon: se pide el stream con ?startIndex y ademas se
    toma el ULTIMO message.completed, no el primero, para que un
    desfase de un evento no cambie el resultado.
    """

    if session_id:
        url = f"{EVE_URL}/eve/v1/session/{session_id}"
    else:
        url = f"{EVE_URL}/eve/v1/session"

    body = json.dumps({"message": message}).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=eve_headers({"content-type": "application/json"}),
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        created = json.loads(response.read().decode("utf-8"))

    session_id = created.get("sessionId") or session_id

    if not session_id:
        raise RuntimeError(f"eve no devolvio sessionId: {created}")

    stream_url = f"{EVE_URL}/eve/v1/session/{session_id}/stream"

    if event_offset > 0:
        stream_url += f"?startIndex={event_offset}"

    answer = None
    delegated = []
    failure = None
    seen = 0

    stream_request = urllib.request.Request(
        stream_url,
        headers=eve_headers(),
    )

    with urllib.request.urlopen(stream_request, timeout=180) as stream:

        for raw in stream:

            seen += 1

            line = raw.decode("utf-8", errors="replace").strip()

            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = event.get("type", "")
            data = event.get("data") or {}

            if kind == "actions.requested":

                for action in data.get("actions") or []:

                    if action.get("kind") == "subagent-call":
                        name = action.get("name") or action.get("subagentName")
                        delegated.append(name)
                        print(f"  -> delegando en el subagente: {name}")

            elif kind == "message.completed":
                answer = data.get("message")

            elif kind in ("turn.failed", "session.failed"):
                failure = data.get("message") or str(data)

            elif kind == "session.waiting":
                break

    if failure and not answer:
        raise RuntimeError(f"eve fallo: {failure}")

    return answer, session_id, event_offset + seen


# ======================================================
# TTS
# ======================================================

def create_tts_wav(voice, text):
    """
    Genera el WAV hablando a SAPI5 directamente.

    NO se usa pyttsx3 a proposito: su driver de SAPI5 se cuelga
    en el SEGUNDO runAndWait() del mismo proceso (comprobado en
    2026-08-27, el proceso quedaba colgado indefinidamente). Eso
    daba igual en speak.py, que hablaba una vez y terminaba, pero
    aqui el puente habla en bucle. SAPI directo aguanta llamadas
    seguidas sin problema.
    """

    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = handle.name
    handle.close()

    stream = CreateObject("SAPI.SpFileStream")
    stream.Open(path, SpeechLib.SSFMCreateForWrite)

    try:
        voice.AudioOutputStream = stream
        voice.Speak(text)
    finally:
        stream.Close()

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("SAPI no genero audio.")

    return path


def convert_audio(input_path):

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

    filters = []

    if LOUDNESS_FILTER:
        filters.append(LOUDNESS_FILTER)

    if VOLUME != 1.0:
        filters.append(f"volume={VOLUME}")

    if filters:
        command += ["-af", ",".join(filters)]

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

        if channels != 1:
            raise ValueError("El audio no quedo mono.")

        if width != 2:
            raise ValueError("El audio no quedo PCM 16-bit.")

        if rate != SAMPLE_RATE:
            raise ValueError(f"El audio no quedo en {SAMPLE_RATE} Hz.")

        return wav.readframes(frames)


def speak(ser, voice, text):

    raw_path = None
    pcm_path = None

    try:

        raw_path = create_tts_wav(voice, text)
        pcm_path = convert_audio(raw_path)
        pcm = load_pcm(pcm_path)

        send_pcm(ser, pcm)

    finally:

        for path in (raw_path, pcm_path):
            if path and os.path.exists(path):
                os.remove(path)


def build_tts_voice():

    voice = CreateObject("SAPI.SpVoice")

    tokens = voice.GetVoices()
    chosen = None

    for index in range(tokens.Count):

        token = tokens.Item(index)

        if VOICE_MATCH.upper() in token.Id.upper():
            chosen = token
            break

    if chosen is not None:
        voice.Voice = chosen
        print("Voz:", chosen.GetDescription())
    else:
        print(f"Aviso: no encontre voz con {VOICE_MATCH} - usando la de por defecto.")

    voice.Rate = VOICE_RATE

    return voice


# ======================================================
# MAIN
# ======================================================

def main():

    print("=" * 46)
    print("KIRA")
    print("=" * 46)
    print()

    if not wait_for_eve():
        print(f"FALLO: eve no responde en {EVE_URL}")
        print()
        print("Arrancalo en otra terminal:")
        print("    cd brain")
        print("    npm exec -- eve dev --no-ui")
        return 1

    print(f"eve listo en {EVE_URL}")

    if not AGENT_TOKEN:
        print()
        print("AVISO: sin KIRA_AGENT_TOKEN. Funcionara contra `eve dev`, pero")
        print("       `eve start` (produccion) devolvera 401.")

    print(f"Cargando Whisper ({WHISPER_MODEL})...")

    model = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type="int8",
    )

    print("Whisper listo.")

    voice = build_tts_voice()

    ser = None
    session_id = None

    # Cuantos eventos del stream de eve ya consumimos. El stream se
    # reproduce desde el evento 0 en cada lectura, asi que sin esto
    # la segunda pregunta devolveria la respuesta de la primera.
    event_offset = 0

    try:

        ser = open_port(find_port())

        if not wait_ready(ser):
            raise RuntimeError(
                "El ESP32 no respondio al PING. "
                "Revisar puerto, baud y que el firmware este subido."
            )

        print("ESP32 listo")
        print()
        print('Di: "Oye Kira..."')
        print()

        audio = bytearray()
        recording = False

        while True:

            frame = read_up_frame(ser)

            if frame is None:
                continue

            frame_type, payload = frame

            if frame_type == UP_LEVEL:

                # Telemetria de calibracion. El firmware calcula
                # los umbrales sobre el ruido de fondo medido en
                # vivo; esto deja ver esos numeros reales.
                if SHOW_LEVELS and not recording and len(payload) >= 4:

                    level, noise = struct.unpack("<HH", payload[:4])

                    voice_th = max(int(noise * 3.0), 250)
                    silence_th = max(int(noise * 1.8), 80)

                    print(
                        f"\r  nivel {level:6d} | ruido {noise:6d} "
                        f"| voz>{voice_th:6d} | fin<{silence_th:6d}   ",
                        end="",
                        flush=True,
                    )

                continue

            if frame_type == UP_START:

                audio = bytearray()
                recording = True

                # Salto de linea: la telemetria escribe con \r
                # sin avanzar, asi no la sobreescribe.
                print()
                print("Escuchando...")

                continue

            if frame_type == UP_AUDIO:

                if recording:
                    audio.extend(payload)

                continue

            if frame_type != UP_END:
                continue

            if not recording:
                continue

            recording = False

            raw_seconds = len(audio) / 2 / SAMPLE_RATE

            # La pausa que cierra la frase queda grabada al final.
            # Con SILENCE_STOP_MS en 3 s eso son 3 s de silencio
            # que Whisper transcribiria para nada.
            audio = trim_trailing_silence(bytes(audio))

            seconds = len(audio) / 2 / SAMPLE_RATE

            peak = struct.unpack("<H", payload)[0] if len(payload) >= 2 else 0

            trimmed = raw_seconds - seconds

            print(
                f"Fin de voz: {seconds:.2f} s "
                f"(recortados {trimmed:.2f} s de pausa) | pico {peak}/32767"
            )

            # El pico permite ajustar MIC_SHIFT del firmware con
            # una medida real en vez de a ojo.
            #
            # El aviso de senal debil solo tiene sentido en algo
            # que de verdad sea una frase: un golpe corto da un
            # pico bajo sin que la ganancia este mal.
            if peak >= 32767:
                print("  AVISO: recorte. Sube MIC_SHIFT en 1 en el firmware.")
            elif 0 < peak < 3000 and seconds >= 1.0:
                print("  AVISO: senal debil. Baja MIC_SHIFT en 1 en el firmware.")

            text = transcribe(model, audio)

            if not text:
                print("No entendi el audio.")
                print()
                ser.reset_input_buffer()
                continue

            print(f'Escuche: "{text}"')

            if not contains_wake_word(text):
                print("Sin wake word. Ignorando.")
                print()
                ser.reset_input_buffer()
                continue

            message = remove_wake_word(text)

            if not message:
                print("Dijiste Oye Kira, pero sin instruccion.")
                print()
                ser.reset_input_buffer()
                continue

            print(f'Instruccion: "{message}"')
            print("Pensando...")

            try:

                if REUSE_SESSION:
                    answer, session_id, event_offset = eve_send(
                        message, session_id, event_offset
                    )
                else:
                    answer, _, _ = eve_send(message, None, 0)

            except Exception as error:

                print("FALLO eve:", error)
                answer = "Tuve un problema al procesar tu peticion."

            if not answer:
                answer = "No supe que responder."

            print(f'Kira dice: "{answer}"')

            speak(ser, voice, answer)

            # Descartar lo que el ESP32 haya podido enviar mientras
            # pensabamos, para no encolar frases viejas.
            ser.reset_input_buffer()

            print()
            print('Di: "Oye Kira..."')
            print()

    except KeyboardInterrupt:

        print()
        print("Saliendo.")

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


if __name__ == "__main__":
    sys.exit(main())
