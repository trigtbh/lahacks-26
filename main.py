import difflib
import io
import os
import struct
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from elevenlabs.client import AsyncElevenLabs
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

client_elevenlabs = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

# In-memory store: chunk_id -> {"chunks": [bytes, ...], "meta": {...}}
recording_store: dict[str, dict] = {}


class AudioSessionRequest(BaseModel):
    chunk_id: str
    user_id: str


@app.get("/")
async def serve_index():
    return FileResponse("index.html")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bit_depth,
        b"data",
        data_size,
    )
    return header + pcm_data


_FLUX_VARIANTS      = ["flux", "flock", "flex", "flocks", "flax", "fluke", "blacks"]
_WORKFLOW_VARIANTS  = ["workflow", "workload", "work-flow", "work"]

def _word_fuzzy_matches(word: str, targets: list, threshold: float = 0.75) -> bool:
    w = word.lower().strip(".,!?\"'-")
    return any(difflib.SequenceMatcher(None, w, t).ratio() >= threshold for t in targets)

def _normalize_pcm(pcm: bytes, target_peak: float = 0.9) -> bytes:
    """Scale 16-bit PCM so the loudest sample hits target_peak of full scale."""
    count = len(pcm) // 2
    if count == 0:
        return pcm
    samples = struct.unpack(f"<{count}h", pcm)
    peak = max(abs(s) for s in samples)
    if peak == 0:
        return pcm
    scale = min((32767 * target_peak) / peak, 8.0)  # cap at 8x to avoid over-amplifying pure noise
    clamped = [max(-32768, min(32767, int(s * scale))) for s in samples]
    return struct.pack(f"<{count}h", *clamped)


def _extract_after_flux(transcript: str) -> str:
    """Return everything after the first flux-like word, or '' if none found."""
    words = transcript.split()
    for i, word in enumerate(words):
        if _word_fuzzy_matches(word, _FLUX_VARIANTS):
            return " ".join(words[i + 1:]).lstrip(" .,").strip()
    return ""

def _contains_workflow(transcript: str) -> bool:
    words = transcript.split()
    if any(_word_fuzzy_matches(w, _WORKFLOW_VARIANTS) for w in words):
        return True
    return "work flow" in transcript.lower()


# ---------------------------------------------------------------------------
# /audio/start  — open a new recording session
# ---------------------------------------------------------------------------

@app.post("/audio/start")
async def audio_start(payload: AudioSessionRequest, request: Request):
    chunk_id = payload.chunk_id
    recording_store[chunk_id] = {
        "chunks": [],
        "meta": {
            "sample_rate": int(request.headers.get("X-Audio-Sample-Rate", 48000)),
            "encoding":    request.headers.get("X-Audio-Encoding", "webm").lower(),
            "channels":    int(request.headers.get("X-Audio-Channels", 1)),
            "user_id":     payload.user_id,
        },
    }
    logger.info(f"[audio/start] chunk_id={chunk_id} meta={recording_store[chunk_id]['meta']}")
    return JSONResponse({"chunk_id": chunk_id, "status": "started"})


# ---------------------------------------------------------------------------
# /audio/stream  — append a chunk to an existing recording session
# ---------------------------------------------------------------------------

@app.post("/audio/stream")
async def audio_stream(request: Request):
    chunk_id = request.headers.get("X-Chunk-Id", "")
    if not chunk_id or chunk_id not in recording_store:
        raise HTTPException(status_code=404, detail=f"Unknown or missing chunk_id: {chunk_id!r}")

    chunk = await request.body()
    if not chunk:
        raise HTTPException(status_code=400, detail="Empty chunk body.")

    recording_store[chunk_id]["chunks"].append(chunk)
    total = sum(len(c) for c in recording_store[chunk_id]["chunks"])
    logger.info(f"[audio/stream] chunk_id={chunk_id} chunk={len(chunk)}B total={total}B")

    # Transcription happens at /audio/end; return a valid shape for the Android client.
    return JSONResponse({"transcript": "", "partial": True})


# ---------------------------------------------------------------------------
# /audio/end  — finalise the session and transcribe
# ---------------------------------------------------------------------------

@app.post("/audio/end")
async def audio_end(payload: AudioSessionRequest):
    chunk_id = payload.chunk_id
    if not chunk_id or chunk_id not in recording_store:
        raise HTTPException(status_code=404, detail=f"Unknown or missing chunk_id: {chunk_id!r}")

    session = recording_store.pop(chunk_id)
    chunks = session["chunks"]
    meta   = session["meta"]

    if not chunks:
        raise HTTPException(status_code=400, detail="No audio chunks were received for this recording.")

    audio_data = b"".join(chunks)
    logger.info(f"[audio/end] chunk_id={chunk_id} total={len(audio_data)}B encoding={meta['encoding']}")

    if meta["encoding"] == "pcm_s16le":
        audio_bytes = _build_wav(_normalize_pcm(audio_data), sample_rate=meta["sample_rate"],
                                  channels=meta["channels"], bit_depth=16)
        filename = "audio.wav"
    else:
        audio_bytes = audio_data
        filename = "audio.webm"

    try:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename
        logger.info(f"[audio/end] sending {len(audio_bytes)}B to ElevenLabs filename={filename}")
        result = await client_elevenlabs.speech_to_text.convert(
            file=audio_file,
            model_id="scribe_v2",
            language_code="en",
            tag_audio_events=False,
            keyterms=["Flux", "workflow"],
        )
        transcript = result.text
        logger.info(f"[audio/end] transcript={transcript!r}")
    except Exception as e:
        logger.error(f"[audio/end] ElevenLabs error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"ElevenLabs transcription failed: {e}")

    command = _extract_after_flux(transcript)
    logger.info(f"[audio/end] command after flux={command!r}")

    return JSONResponse({
        "chunk_id": chunk_id,
        "user_id": meta["user_id"],
        "transcript": transcript,
        "command": command,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
