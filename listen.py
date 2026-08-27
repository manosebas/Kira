import serial
import struct
import wave
import tempfile
import os
import re
import time

from faster_whisper import WhisperModel


# ======================================================
# CONFIG
# ======================================================

PORT = "COM5"
BAUD = 921600

SAMPLE_RATE = 16000

MAGIC = b"\xAA\x55"

FRAME_START = 1
FRAME_AUDIO = 2
FRAME_END = 3


# ======================================================
# WHISPER
# ======================================================

print("Cargando Whisper...")

model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8"
)

print("Whisper listo.")
print()


# ======================================================
# SERIAL
# ======================================================

ser = serial.Serial(
    PORT,
    BAUD,
    timeout=1
)

ser.reset_input_buffer()


# ======================================================
# FUNCIONES
# ======================================================

def read_exactly(count):

    data = bytearray()

    while len(data) < count:

        chunk = ser.read(
            count - len(data)
        )

        if chunk:
            data.extend(chunk)

    return bytes(data)


def transcribe_audio(audio):

    if len(audio) < 2000:
        return None

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            delete=False
        ) as temp:

            temp_path = temp.name


        with wave.open(
            temp_path,
            "wb"
        ) as wav:

            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(audio)


        segments, info = model.transcribe(
            temp_path,
            language="es",
            beam_size=5,
            vad_filter=True
        )


        text = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()


        return text


    finally:

        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


# ======================================================
# NORMALIZAR TEXTO
# ======================================================

def normalize_text(text):

    normalized = text.lower()

    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ü": "u"
    }

    for original, replacement in replacements.items():
        normalized = normalized.replace(
            original,
            replacement
        )

    return normalized


# ======================================================
# DETECTAR WAKE WORD
# ======================================================

def contains_wake_word(text):

    normalized = normalize_text(text)

    patterns = [
        r"\boye kira\b",
        r"\boye, kira\b",
        r"\boie kira\b",
    ]

    return any(
        re.search(pattern, normalized)
        for pattern in patterns
    )


# ======================================================
# QUITAR "OYE KIRA"
# ======================================================

def remove_wake_word(text):

    # Trabajamos sobre el texto original
    # para conservar mayúsculas y acentos.

    pattern = re.compile(
        r"^\s*oye[\s,]+kira[\s,.:;!?-]*",
        re.IGNORECASE
    )

    clean_text = pattern.sub(
        "",
        text
    ).strip()

    return clean_text


# ======================================================
# API SIMULADA
# ======================================================

def send_to_fake_api(message):

    print()
    print("🌐 Enviando al API simulada...")
    print(f'Payload: "{message}"')

    # Simulamos un pequeño tiempo de red
    time.sleep(0.8)

    # Aquí luego irá requests.post(...)
    fake_response = (
        f"API SIMULADA recibió correctamente: {message}"
    )

    return fake_response


# ======================================================
# INICIO
# ======================================================

print("==============================")
print("KIRA")
print("==============================")
print()
print('Di: "Oye Kira..."')
print()


audio_buffer = bytearray()
recording = False


# ======================================================
# LOOP PRINCIPAL
# ======================================================

while True:

    # Buscar primer byte MAGIC
    byte = ser.read(1)

    if byte != b"\xAA":
        continue


    # Buscar segundo byte MAGIC
    byte2 = ser.read(1)

    if byte2 != b"\x55":
        continue


    # Leer tipo de frame
    frame_type = read_exactly(1)[0]


    # Leer longitud
    length_bytes = read_exactly(2)

    length = struct.unpack(
        "<H",
        length_bytes
    )[0]


    payload = b""

    if length > 0:
        payload = read_exactly(length)


    # ==================================================
    # START
    # ==================================================

    if frame_type == FRAME_START:

        audio_buffer = bytearray()
        recording = True

        print()
        print("🎤 Escuchando...")


    # ==================================================
    # AUDIO
    # ==================================================

    elif (
        frame_type == FRAME_AUDIO
        and recording
    ):

        audio_buffer.extend(payload)


    # ==================================================
    # END
    # ==================================================

    elif frame_type == FRAME_END:

        if not recording:
            continue


        recording = False


        seconds = (
            len(audio_buffer)
            /
            2
            /
            SAMPLE_RATE
        )


        print(
            f"⏹ Fin de voz ({seconds:.2f} s)"
        )

        print("🧠 Convirtiendo a texto...")


        text = transcribe_audio(
            audio_buffer
        )


        if not text:

            print("❌ No pude entender el audio.")
            print()
            print('Di: "Oye Kira..."')

            continue


        print()
        print(f'📝 Escuché: "{text}"')


        # ==============================================
        # WAKE WORD
        # ==============================================

        if contains_wake_word(text):

            print("✅ OYE KIRA DETECTADO")


            message = remove_wake_word(
                text
            )


            if not message:

                print()
                print(
                    "⚠ Dijiste Oye Kira, "
                    "pero no encontré una instrucción."
                )

                print()
                print('Di: "Oye Kira..."')

                continue


            print()
            print(
                f'📤 Mensaje útil: "{message}"'
            )


            # ==========================================
            # API
            # ==========================================

            response = send_to_fake_api(
                message
            )


            print()
            print("🤖 Respuesta de Kira:")
            print(response)


        else:

            print()
            print(
                "⚪ No dijiste Oye Kira. "
                "Ignorando."
            )


        print()
        print("==============================")
        print('Di: "Oye Kira..."')
        print()