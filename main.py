import io
import os
import struct
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from elevenlabs.client import ElevenLabs
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

client_elevenlabs = ElevenLabs(api_key=ELEVENLABS_API_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/")
async def serve_index():
    return FileResponse("index.html")


def _build_wav(pcm_data: bytes, sample_rate: int, channels: int, bit_depth: int = 16) -> bytes:
    """Wrap raw PCM bytes in a minimal WAV (RIFF) container."""
    byte_rate = sample_rate * channels * (bit_depth // 8)
    block_align = channels * (bit_depth // 8)
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,           # PCM sub-chunk size
        1,            # audio format (PCM)
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bit_depth,
        b"data",
        data_size,
    )
    return header + pcm_data


@app.post("/transcribe")
async def transcribe_audio(request: Request):
    """
    Receive a complete audio transmission as raw application/octet-stream
    (PCM s16le) and transcribe it using ElevenLabs Scribe.

    Expected request headers:
        X-Audio-Sample-Rate : int   (e.g. 16000)
        X-Audio-Encoding    : str   (e.g. pcm_s16le)
        X-Audio-Channels    : int   (e.g. 1)
        X-User-Id           : str   (caller identity)
    """
    sample_rate = int(request.headers.get("X-Audio-Sample-Rate", 16000))
    encoding    = request.headers.get("X-Audio-Encoding", "pcm_s16le").lower()
    channels    = int(request.headers.get("X-Audio-Channels", 1))
    user_id     = request.headers.get("X-User-Id", "unknown")

    logger.info(f"[transcribe] user={user_id} sample_rate={sample_rate} encoding={encoding} channels={channels}")

    pcm_data = await request.body()
    if not pcm_data:
        raise HTTPException(status_code=400, detail="Empty audio body received.")

    logger.info(f"[transcribe] user={user_id} received {len(pcm_data)} bytes of PCM audio")

    if encoding == "pcm_s16le":
        audio_bytes = _build_wav(pcm_data, sample_rate=sample_rate, channels=channels, bit_depth=16)
        filename = "audio.wav"
    else:
        # Browser-recorded formats (webm, ogg, etc.) — send as-is
        audio_bytes = pcm_data
        filename = "audio.webm"

    try:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename

        result = client_elevenlabs.speech_to_text.convert(
            file=audio_file,
            model_id="scribe_v2",
        )
        transcript = result.text
        logger.info(f"[transcribe] user={user_id} transcript: {transcript!r}")
    except Exception as e:
        logger.error(f"[transcribe] ElevenLabs error for user={user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"ElevenLabs transcription failed: {e}")

    return JSONResponse({"user_id": user_id, "transcript": transcript})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
