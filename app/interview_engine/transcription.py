import os

from groq import Groq

MODEL = "whisper-large-v3"


def transcribe_audio(filename: str, audio_bytes: bytes) -> str:
    """Transcribes a recording via Groq's hosted Whisper API.

    filename just needs to keep the original extension (e.g. "x.wav") so Groq
    can infer the audio format — the bytes are what actually get transcribed.
    Raises on failure; the caller (a background job) is responsible for
    catching and recording that failure since there's no request left by then.
    """
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    transcription = client.audio.transcriptions.create(
        model=MODEL,
        file=(filename, audio_bytes),
        response_format="json",
    )
    return transcription.text
