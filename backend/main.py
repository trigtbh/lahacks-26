from dotenv import load_dotenv
load_dotenv()
import difflib
import os
import re
import base64
import struct
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from elevenlabs.client import AsyncElevenLabs
from deepgram import DeepgramClient, PrerecordedOptions


from agentverse_client import find_agent, send_to_agent, start_gateway
import session_store as sessions

# ── Workflow pipeline ─────────────────────────────────────────────────────────
import asyncio
import workflow_store
import zapier_store
from executor import execute_workflow
from ai.classifier import classify
from ai.validator import validate

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")  # "George"
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")

client_elevenlabs = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)
client_deepgram = DeepgramClient(api_key=DEEPGRAM_API_KEY)


async def _tts_pcm(text: str) -> str | None:
    """TTS text via ElevenLabs → base64-encoded PCM 16kHz mono. Returns None on failure."""
    if not text or not ELEVENLABS_API_KEY:
        return None
    try:
        chunks: list[bytes] = []
        async for chunk in client_elevenlabs.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            text=text,
            model_id="eleven_turbo_v2_5",
            output_format="pcm_16000",
        ):
            chunks.append(chunk)
        pcm = b"".join(chunks)
        return base64.b64encode(pcm).decode()
    except Exception as e:
        logger.error(f"[tts] ElevenLabs TTS error: {e}")
        return None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Intent patterns ──────────────────────────────────────────────────────────

_CONNECT_RE = re.compile(
    r"\b(connect|talk|speak|open|switch|use|get|find|call)\b.{0,20}\b(?:to|with)?\b\s+(?:the\s+)?(?P<name>\w[\w\s]{0,30}?)\s*(?:agent)?$",
    re.IGNORECASE,
)
_DISCONNECT_RE = re.compile(r"\b(disconnect|stop|exit|end|close|bye)\b", re.IGNORECASE)


def _parse_connect_intent(text: str) -> str | None:
    """Return agent name if the transcript is a connect request, else None."""
    m = _CONNECT_RE.search(text.strip())
    return m.group("name").strip() if m else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_gateway()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store: chunk_id -> {"chunks": [bytes, ...], "meta": {...}}
recording_store: dict[str, dict] = {}


class AudioSessionRequest(BaseModel):
    chunk_id: str
    user_id: str


_BASE_DIR = Path(__file__).parent


@app.get("/")
async def serve_index():
    return FileResponse(_BASE_DIR / "index.html")


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

_COMMAND_VARIANTS = {
    "workflow": [
        "create a workflow", "create workflow", "make a workflow", "make workflow",
        "build a workflow", "build workflow", "start a workflow", "new workflow",
    ],
    "caltrain": [
        "talk to caltrain", "caltrain", "talk to cal train", "cal train",
        "train schedule", "next train", "train times",
    ],
}

_AGENTVERSE_VARIANTS = ["agentverse", "agent verse", "agentaverse", "agentoverse"]

# Agent addresses that bypass the agentverse search
_HARDCODED_AGENTS: dict[str, tuple[str, str]] = {
    "caltrain": (
        "agent1qtuuyttz8ujuxceq0gllcerlksjneenrh2mfcm67st8qrm9lzzh3cd7f9h6",
        "Caltrain",
    ),
}

_FIND_AGENT_RE = re.compile(
    r"\b(?:find|search\s+for|search|look\s+up)\s+(?P<name>.+?)\s+(?:on|in|at)\s+\S+$",
    re.IGNORECASE,
)

def _word_fuzzy_matches(word: str, targets: list, threshold: float = 0.75) -> bool:
    w = word.lower().strip(".,!?\"'-")
    return any(difflib.SequenceMatcher(None, w, t).ratio() >= threshold for t in targets)

def _extract_agentverse_search(command: str) -> str | None:
    """If command is a fuzzy 'find X on agentverse' pattern, return agent name X."""
    words = command.lower().split()
    if not any(_word_fuzzy_matches(w, _AGENTVERSE_VARIANTS) for w in words):
        return None
    m = _FIND_AGENT_RE.search(command)
    return m.group("name").strip() if m else None

def _classify_command(command: str) -> tuple[str, str]:
    """Return (action, agent_name). agent_name is non-empty only for agentverse_search."""
    if not command:
        return "unknown", ""

    agent_name = _extract_agentverse_search(command)
    if agent_name:
        logger.info(f"[classify] command={command!r} action=agentverse_search agent={agent_name!r}")
        return "agentverse_search", agent_name

    text = command.lower().strip()
    best_action, best_score = "unknown", 0.4
    for action, variants in _COMMAND_VARIANTS.items():
        for variant in variants:
            score = difflib.SequenceMatcher(None, text, variant).ratio()
            if score > best_score:
                best_score = score
                best_action = action
    logger.info(f"[classify] command={command!r} action={best_action} score={best_score:.2f}")
    return best_action, ""

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


async def _create_workflow_from_transcript(user_id: str, transcript: str) -> dict:
    logger.info("[audio/workflow] classifying transcript=%r user=%s", transcript, user_id)
    try:
        workflow = await asyncio.to_thread(classify, transcript)
    except Exception as exc:
        logger.error("[audio/workflow] classify failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Workflow classification failed: {exc}")

    validation_errors = validate(workflow)
    if validation_errors:
        logger.warning("[audio/workflow] validation errors: %s", validation_errors)

    trigger_phrase = workflow.get("trigger_phrase", "").strip()
    steps = workflow.get("steps", [])
    if not trigger_phrase:
        raise HTTPException(status_code=422, detail="Classifier returned no trigger_phrase")
    if not steps:
        raise HTTPException(status_code=422, detail="Classifier returned no workflow steps")

    existing_workflow = await workflow_store.find_by_trigger(user_id, trigger_phrase)
    if existing_workflow:
        logger.info("[audio/workflow] classifier trigger matched existing workflow trigger=%r user=%s",
                    trigger_phrase, user_id)
        return await _execute_saved_workflow(existing_workflow, user_id)

    workflow_id = await workflow_store.save_workflow(
        user_id=user_id,
        trigger_phrase=trigger_phrase,
        steps=steps,
    )
    logger.info("[audio/workflow] created id=%s trigger=%r user=%s",
                workflow_id, trigger_phrase, user_id)

    return {
        "workflow_status": "created",
        "workflow_message": "workflow created",
        "workflow_id": workflow_id,
        "workflow_trigger": trigger_phrase,
        "workflow_schema": {
            "trigger_phrase": trigger_phrase,
            "steps": steps,
            "missing_params": workflow.get("missing_params", []),
            "confidence": workflow.get("confidence"),
            "validation_errors": validation_errors,
        },
    }


async def _execute_saved_workflow(doc: dict, user_id: str) -> dict:
    workflow_id = str(doc.get("_id", ""))
    logger.info("[audio/workflow] executing id=%s trigger=%r user=%s",
                workflow_id, doc.get("trigger_phrase"), user_id)

    result = await execute_workflow(user_id, doc["steps"])
    return {
        "workflow_status": "executed",
        "workflow_message": "workflow executed",
        "workflow_id": workflow_id,
        "workflow_trigger": doc.get("trigger_phrase", ""),
        "workflow_result": result,
    }


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
        logger.info(f"[audio/end] sending {len(audio_bytes)}B to Deepgram filename={filename}")
        options = PrerecordedOptions(
            model="nova-3",
            language="en",
            smart_format=True,
        )
        response = await client_deepgram.listen.asyncrest.v("1").transcribe_file(
            {"buffer": audio_bytes, "mimetype": mime_type},
            options,
        )
        transcript = (
            response.results.channels[0].alternatives[0].transcript
            if response.results and response.results.channels
            else ""
        )
        logger.info(f"[audio/end] transcript={transcript!r}")
    except Exception as e:
        logger.error(f"[audio/end] Deepgram error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Deepgram transcription failed: {e}")

    command = _extract_after_flux(transcript)
    action, agent_name = _classify_command(command)
    logger.info(f"[audio/end] command={command!r} action={action} agent_name={agent_name!r}")

    workflow_response = None
    workflow_spoken_text = command.strip() or transcript.strip()
    if workflow_spoken_text:
        existing_workflow = await workflow_store.find_by_trigger(meta["user_id"], workflow_spoken_text)
        if existing_workflow:
            workflow_response = await _execute_saved_workflow(existing_workflow, meta["user_id"])
            action = "workflow"
            agent_name = ""
        elif action == "workflow" or _contains_workflow(workflow_spoken_text):
            workflow_response = await _create_workflow_from_transcript(meta["user_id"], workflow_spoken_text)
            action = "workflow"
            agent_name = ""

    response = {
        "chunk_id": chunk_id,
        "user_id": meta["user_id"],
        "transcript": transcript,
        "command": command,
        "action": action,
        "agent_name": agent_name,
    }
    if workflow_response:
        response.update(workflow_response)

    return JSONResponse(response)


# ---------------------------------------------------------------------------
# /workflow/execute  — route transcript to active agent or built-in workflow
# ---------------------------------------------------------------------------

class WorkflowRequest(BaseModel):
    trigger_phrase: str
    user_id: str
    context: dict = {}


@app.post("/workflow/execute")
async def workflow_execute(payload: WorkflowRequest):
    text = payload.trigger_phrase.strip()
    user_id = payload.user_id
    logger.info(f"[workflow/execute] user={user_id} text={text!r}")

    async def _respond(action: str, steps: list[str], reply: str, needs_input: bool = False) -> JSONResponse:
        audio_b64 = await _tts_pcm(reply)
        return JSONResponse({
            "action_taken": action,
            "steps_completed": steps,
            "needs_input": needs_input,
            "question": reply if needs_input else "",
            "reply": reply,
            "audio_b64": audio_b64,
        })

    # 1. Disconnect intent
    if _DISCONNECT_RE.search(text):
        session = sessions.get_session(user_id)
        if session:
            agent_name = session.agent_name
            sessions.end_session(user_id)
            return await _respond("disconnect", [f"Disconnected from {agent_name}"],
                                  f"Disconnected from {agent_name}.")

    # 2. Connect intent — "talk to Caltrain"
    raw_name = _parse_connect_intent(text)
    if raw_name:
        hardcoded = _HARDCODED_AGENTS.get(raw_name.lower())
        if hardcoded:
            address, display_name = hardcoded
            logger.info(f"[workflow/execute] user={user_id} → hardcoded agent={display_name} addr={address}")
        else:
            result = await find_agent(raw_name)
            if not result:
                return await _respond("connect_failed", [],
                                      f"Sorry, I couldn't find an agent named '{raw_name}' on Agentverse.")
            address, display_name = result
        sessions.start_session(user_id, address, display_name)
        logger.info(f"[workflow/execute] user={user_id} → agent={display_name} addr={address}")
        return await _respond("connect", [f"Connected to {display_name}"],
                              f"Connected to {display_name}. Go ahead.")

    # 3. Route to active agent session via uAgents gateway
    session = sessions.get_session(user_id)
    if session:
        sessions.append_history(user_id, "user", text)
        try:
            reply = await send_to_agent(session.agent_address, text, user_id)
        except TimeoutError:
            reply = "The agent didn't respond in time. Try again."
        except Exception as e:
            logger.error(f"[workflow/execute] gateway error: {e}", exc_info=True)
            reply = "Something went wrong reaching the agent. Try again."
        sessions.append_history(user_id, "agent", reply)
        return await _respond("agent_message", [f"Sent to {session.agent_name}"], reply)

    # 4. No active session — fallback
    # Relaxed the fallback to avoid spamming the user on random background noise.
    return await _respond("no_agent", [], "")


# ---------------------------------------------------------------------------
# /agent/chat  — lightweight direct chat endpoint (bypasses audio pipeline)
# ---------------------------------------------------------------------------

class AgentChatRequest(BaseModel):
    user_id: str
    message: str


@app.post("/agent/chat")
async def agent_chat(payload: AgentChatRequest):
    """Direct text → agent → text endpoint for testing or non-audio clients."""
    fake_workflow = WorkflowRequest(
        trigger_phrase=payload.message,
        user_id=payload.user_id,
    )
    return await workflow_execute(fake_workflow)


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class WorkflowCreateRequest(BaseModel):
    user_id:    str
    transcript: str   # natural language, e.g. "When I say I'm running late, ..."


class WorkflowTriggerRequest(BaseModel):
    user_id:        str
    trigger_phrase: str


# ---------------------------------------------------------------------------
# POST /workflow/create
# Classify a natural-language transcript → workflow schema → save to MongoDB.
# ---------------------------------------------------------------------------
@app.post("/workflow/create")
async def workflow_create(payload: WorkflowCreateRequest):
    """
    Turn a natural-language transcript into a workflow schema and persist it.

    Example body:
    {
      "user_id": "user123",
      "transcript": "When I say I'm running late, shift my next meeting by 10 mins and email the attendees"
    }

    The AI classifier extracts:
      - trigger_phrase  (the phrase that fires this workflow later)
      - steps           (app/action/params for each action)
    Both are saved to MongoDB and returned.
    """
    # 1. Classify — runs synchronously against Gemini, off the event loop
    logger.info("[workflow/create] classifying transcript=%r user=%s",
                payload.transcript, payload.user_id)
    try:
        workflow = await asyncio.to_thread(classify, payload.transcript)
    except Exception as exc:
        logger.error("[workflow/create] classify failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Classification failed: {exc}")

    # 2. Soft-validate (never blocks — just surfaces errors to the caller)
    errors = validate(workflow)
    if errors:
        logger.warning("[workflow/create] validation errors: %s", errors)

    # 3. Extract what we need to store
    trigger_phrase = workflow.get("trigger_phrase", "").strip()
    steps          = workflow.get("steps", [])

    if not trigger_phrase:
        raise HTTPException(status_code=422, detail="Classifier returned no trigger_phrase")

    # 4. Persist
    workflow_id = await workflow_store.save_workflow(
        user_id=payload.user_id,
        trigger_phrase=trigger_phrase,
        steps=steps,
    )
    logger.info("[workflow/create] saved id=%s trigger=%r user=%s",
                workflow_id, trigger_phrase, payload.user_id)

    return {
        "workflow_id":       workflow_id,
        "trigger_phrase":    trigger_phrase,
        "steps":             steps,
        "missing_params":    workflow.get("missing_params", []),
        "confidence":        workflow.get("confidence"),
        "validation_errors": errors,
    }


# ---------------------------------------------------------------------------
# GET /workflow/list/{user_id}
# ---------------------------------------------------------------------------
@app.get("/workflow/list/{user_id}")
async def workflow_list(user_id: str):
    """Return all saved workflows for a user."""
    workflows = await workflow_store.list_workflows(user_id)
    return {"workflows": workflows}


# ---------------------------------------------------------------------------
# POST /workflow/trigger
# Match a spoken phrase to a saved workflow and execute it.
# ---------------------------------------------------------------------------
@app.post("/workflow/trigger")
async def workflow_trigger(payload: WorkflowTriggerRequest):
    """
    Fire a workflow by trigger phrase.
    Looks up the best matching workflow in MongoDB for this user,
    then executes the Gmail + Google Calendar steps.
    """
    doc = await workflow_store.find_by_trigger(payload.user_id, payload.trigger_phrase)
    if not doc:
        logger.info("[workflow/trigger] no match for %r user=%s",
                    payload.trigger_phrase, payload.user_id)
        return {
            "status":  "no_match",
            "message": f"No workflow found matching '{payload.trigger_phrase}'",
        }

    logger.info("[workflow/trigger] matched trigger=%r id=%s user=%s",
                doc["trigger_phrase"], doc["_id"], payload.user_id)

    result = await execute_workflow(payload.user_id, doc["steps"])

    audio_b64 = None
    if result["status"] == "success":
        n = len(result["steps_completed"])
        summary = f"Done. {n} step{'s' if n != 1 else ''} completed."
        audio_b64 = await _tts_pcm(summary)

    return {
        "status":          result["status"],
        "trigger_matched": doc["trigger_phrase"],
        "steps_completed": result["steps_completed"],
        "steps_failed":    result["steps_failed"],
        "audio_b64":       audio_b64,
    }


# ---------------------------------------------------------------------------
# DELETE /workflow/{workflow_id}
# ---------------------------------------------------------------------------
@app.delete("/workflow/{workflow_id}")
async def workflow_delete(workflow_id: str):
    deleted = await workflow_store.delete_workflow(workflow_id)
    return {"deleted": deleted}


# ═══════════════════════════════════════════════════════════════════════════════
# ZAPIER WEBHOOK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

class WebhookRegisterRequest(BaseModel):
    app:         str
    action:      str
    webhook_url: str
    label:       str = ""


@app.post("/user/{user_id}/webhooks")
async def register_webhook(user_id: str, payload: WebhookRegisterRequest):
    """
    Register (or update) a Zapier webhook URL for a specific app+action.

    Example body:
    { "app": "gmail", "action": "send_email", "webhook_url": "https://hooks.zapier.com/..." }
    """
    doc_id = await zapier_store.save_webhook(
        user_id=user_id,
        app=payload.app,
        action=payload.action,
        webhook_url=payload.webhook_url,
        label=payload.label,
    )
    logger.info("[webhooks] registered user=%s app=%s action=%s", user_id, payload.app, payload.action)
    return {"id": doc_id, "app": payload.app, "action": payload.action, "status": "ok"}


@app.get("/user/{user_id}/webhooks")
async def list_user_webhooks(user_id: str):
    """Return all configured Zapier webhooks for a user."""
    webhooks = await zapier_store.list_webhooks(user_id)
    return {"webhooks": webhooks}


@app.delete("/user/{user_id}/webhooks/{app}/{action}")
async def delete_user_webhook(user_id: str, app: str, action: str):
    """Remove a webhook for a specific app+action."""
    deleted = await zapier_store.delete_webhook(user_id, app, action)
    return {"deleted": deleted}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
