import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
import difflib
import ipaddress
import json
import os
import re
import base64
import struct
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from elevenlabs.client import AsyncElevenLabs
from deepgram import DeepgramClient, PrerecordedOptions


from agentverse_client import find_agent, send_to_agent, start_gateway
import session_store as sessions

# ── Workflow pipeline ─────────────────────────────────────────────────────────
import asyncio
import audit_store
import confirmation_store
import workflow_store
import zapier_store
import token_store
from executor import execute_workflow, execute_workflow_stream, preview_workflow
from ai.classifier import classify, classify_for_user
from ai.validator import validate

SLACK_CLIENT_ID      = os.environ.get("SLACK_CLIENT_ID", "")
print(f"SLACK_CLIENT_ID: {SLACK_CLIENT_ID}")
SLACK_CLIENT_SECRET  = os.environ.get("SLACK_CLIENT_SECRET", "")
NOTION_CLIENT_ID     = os.environ.get("NOTION_CLIENT_ID", "")
NOTION_CLIENT_SECRET = os.environ.get("NOTION_CLIENT_SECRET", "")
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
BACKEND_URL          = os.environ.get("BACKEND_URL", "https://flux.trigtbh.dev")
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI", f"{BACKEND_URL}/connect/google/redirect")


def _load_google_client_config() -> tuple[str, dict]:
    credentials_path = Path(__file__).with_name("credentials.json")
    if not credentials_path.exists():
        return "", {}
    try:
        payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logging.getLogger(__name__).warning("[auth/google] failed reading credentials.json: %s", exc)
        return "", {}
    for client_type in ("installed", "web"):
        config = payload.get(client_type)
        if isinstance(config, dict):
            return client_type, config
    return "", {}


_GOOGLE_CLIENT_TYPE, _GOOGLE_CLIENT_CONFIG = _load_google_client_config()
if not GOOGLE_CLIENT_ID:
    GOOGLE_CLIENT_ID = str(_GOOGLE_CLIENT_CONFIG.get("client_id") or "")
if not GOOGLE_CLIENT_SECRET:
    GOOGLE_CLIENT_SECRET = str(_GOOGLE_CLIENT_CONFIG.get("client_secret") or "")

_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/drive",
    "openid",
    "email",
]
_SLACK_USER_SCOPES = ["chat:write", "channels:read", "im:write"]

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


def _is_private_non_loopback_host(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_private and not address.is_loopback


def _get_google_redirect_uri(request: Request | None = None) -> str:
    configured_redirect = GOOGLE_REDIRECT_URI.strip()
    parsed_configured = urlparse(configured_redirect) if configured_redirect else None

    if request is not None:
        request_host = request.url.hostname or ""
        request_port = request.url.port or 8000
        if _GOOGLE_CLIENT_TYPE == "installed" and _is_private_non_loopback_host(request_host):
            localhost_redirect = f"http://localhost:{request_port}/connect/google/redirect"
            logger.info(
                "[auth/google] using localhost redirect for installed client instead of private host=%s",
                request_host,
            )
            return localhost_redirect

    if parsed_configured and _GOOGLE_CLIENT_TYPE == "installed":
        configured_host = parsed_configured.hostname or ""
        if _is_private_non_loopback_host(configured_host):
            localhost_redirect = f"http://localhost:{parsed_configured.port or 8000}/connect/google/redirect"
            logger.info(
                "[auth/google] overriding private redirect host=%s with localhost for installed client",
                configured_host,
            )
            return localhost_redirect

    if configured_redirect:
        return configured_redirect

    return f"{BACKEND_URL}/connect/google/redirect"

# ── Intent patterns ──────────────────────────────────────────────────────────

_CONNECT_RE = re.compile(
    r"\b(connect|talk|speak|open|switch|use|get|find|call)\b.{0,20}\b(?:to|with)?\b\s+(?:the\s+)?(?P<name>\w[\w\s]{0,30}?)\s*(?:agent)?$",
    re.IGNORECASE,
)
_DISCONNECT_RE = re.compile(r"\b(disconnect|stop|exit|end|close|bye)\b", re.IGNORECASE)
_CONFIRM_RE = re.compile(r"^\s*(yes|yeah|yep|confirm|do it|go ahead|run it|execute it)\s*[.!]?\s*$", re.IGNORECASE)
_DECLINE_RE = re.compile(r"^\s*(no|nope|cancel|stop|don'?t|do not)\s*[.!]?\s*$", re.IGNORECASE)
_EXPLICIT_CREATE_RE = re.compile(
    r"\b("
    r"when i say|whenever i say|if i say|"
    r"create (?:a )?workflow|make (?:a )?workflow|build (?:a )?workflow|new workflow|"
    r"set up (?:a )?workflow|save (?:this )?workflow"
    r")\b",
    re.IGNORECASE,
)


def _parse_connect_intent(text: str) -> str | None:
    """Return agent name if the transcript is a connect request, else None."""
    m = _CONNECT_RE.search(text.strip())
    return m.group("name").strip() if m else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_gateway()
    yield

_BASE_DIR       = Path(__file__).parent
_ONBOARDING_DIR = _BASE_DIR / "static" / "onboarding"

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


_FLUX_VARIANTS      = ["flux", "flock", "flex", "flocks", "flax", "fluke", "blacks", "folks"]
_WORKFLOW_VARIANTS  = ["workflow", "workload", "work-flow", "work"]
_COMMON_FLUX_MISHEARS = {"folks", "fox", "folksy", "flucks"}
_WAKE_PREFIX_RE = re.compile(
    r"^\s*(?:hey|hi|okay|ok)\b[\s,]+(?P<wake>[a-zA-Z']+)\b(?:[\s,!.?]+(?P<rest>.*))?$",
    re.IGNORECASE,
)

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
    wake_prefix_match = _WAKE_PREFIX_RE.match(transcript)
    if wake_prefix_match:
        wake_word = wake_prefix_match.group("wake").lower()
        if wake_word in _COMMON_FLUX_MISHEARS:
            return (wake_prefix_match.group("rest") or "").lstrip(" .,").strip()
    return ""

def _contains_workflow(transcript: str) -> bool:
    words = transcript.split()
    if any(_word_fuzzy_matches(w, _WORKFLOW_VARIANTS) for w in words):
        return True
    return "work flow" in transcript.lower()


def _is_explicit_workflow_creation_request(transcript: str) -> bool:
    return bool(_EXPLICIT_CREATE_RE.search(transcript))


def _preview_failure_message(preview: dict) -> str:
    step_errors = preview.get("step_errors", [])
    labels = [str(step.get("step", "")) for step in step_errors]
    if any(label.startswith("gmail.") for label in labels):
        return "gmail action failed"
    if any(label.startswith("google_calendar.") for label in labels):
        return "calendar action failed"
    if any(label.startswith("slack.") for label in labels):
        return "slack action failed"
    return "workflow preview failed"


def _summarize_schema_step(step: dict) -> str:
    app = str(step.get("app", ""))
    action = str(step.get("action", ""))
    params = step.get("params", {}) if isinstance(step.get("params"), dict) else {}

    if app == "google_calendar" and action == "push_event":
        return f"push the next calendar event by {params.get('by_minutes', '?')} minutes"
    if app == "google_calendar" and action == "create_event":
        return f"create a calendar event {params.get('title', '')}".strip()
    if app == "google_calendar" and action == "cancel_event":
        return "cancel the next calendar event"
    if app == "gmail" and action == "send_email":
        return "send an email"
    if app == "gmail" and action == "draft_email":
        return "draft an email"
    if app == "slack" and action == "send_dm":
        return "send a Slack message"
    if app == "slack" and action == "send_channel":
        return "post in Slack"
    if app == "dominos" and action == "order_pizza":
        size = params.get("size", "large")
        toppings = params.get("toppings", [])
        if isinstance(toppings, list):
            toppings = ", ".join(toppings) if toppings else "cheese"
        return f"order a {size} {toppings} pizza from Domino's"
    if app == "dominos" and action == "reorder_last":
        return "reorder your last Domino's order"
    return f"run {app}.{action}"


def _build_create_preview_from_schema(steps: list[dict]) -> dict:
    preview_steps = []
    for step in steps:
        label = f"{step.get('app', '')}.{step.get('action', '')}"
        preview_steps.append({
            "step": label,
            "params": step.get("params", {}),
            "summary": _summarize_schema_step(step),
            "status": "ready",
        })
    return {
        "status": "ready",
        "steps": preview_steps,
        "step_errors": [],
    }


def _build_confirmation_prompt(kind: str, workflow_trigger: str, preview: dict) -> str:
    ready_steps = preview.get("steps", [])
    summaries = [step.get("summary", "") for step in ready_steps if step.get("summary")]
    short_summaries = ", then ".join(summaries[:2]) if summaries else "run this workflow"

    if kind == "create":
        return (
            f"I can create a workflow for {workflow_trigger}. "
            f"It will {short_summaries}. Say yes to confirm or no to cancel."
        )
    return (
        f"I matched the workflow {workflow_trigger}. "
        f"I will {short_summaries}. Say yes to confirm or no to cancel."
    )


async def _classify_workflow_request(user_id: str, transcript: str) -> tuple[dict, list[str]]:
    logger.info("[audio/workflow] classifying transcript=%r user=%s", transcript, user_id)
    try:
        workflow = await classify_for_user(transcript, user_id)
    except Exception as exc:
        logger.error("[audio/workflow] classify failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Workflow classification failed: {exc}")

    if workflow.get("intent") == "denied":
        reason = workflow.get("denial_reason", "None of your connected apps can handle that request.")
        logger.info("[audio/workflow] denied: %s user=%s", reason, user_id)
        return {"workflow_status": "denied", "workflow_message": reason}

    validation_errors = validate(workflow)
    if validation_errors:
        logger.warning("[audio/workflow] validation errors: %s", validation_errors)

    trigger_phrase = workflow.get("trigger_phrase", "").strip()
    steps = workflow.get("steps", [])
    if not trigger_phrase:
        raise HTTPException(status_code=422, detail="Classifier returned no trigger_phrase")
    if not steps:
        raise HTTPException(status_code=422, detail="Classifier returned no workflow steps")

    return workflow, validation_errors


async def _queue_confirmation(
    *,
    user_id: str,
    kind: str,
    transcript: str,
    command_text: str,
    workflow_id: str,
    workflow_trigger: str,
    steps: list[dict],
    preview: dict,
    workflow_schema: dict,
    audit_id: str,
) -> dict:
    confirmation_store.set_pending(confirmation_store.PendingConfirmation(
        user_id=user_id,
        kind=kind,
        command_text=command_text,
        transcript=transcript,
        workflow_id=workflow_id,
        workflow_trigger=workflow_trigger,
        steps=steps,
        preview=preview,
        workflow_schema=workflow_schema,
        audit_id=audit_id,
    ))
    confirmation_prompt = _build_confirmation_prompt(kind, workflow_trigger, preview)
    logger.info("[audio/workflow] queued %s confirmation trigger=%r user=%s", kind, workflow_trigger, user_id)
    return {
        "workflow_status": "awaiting_confirmation",
        "workflow_message": confirmation_prompt,
        "workflow_id": workflow_id,
        "workflow_trigger": workflow_trigger,
        "workflow_preview": preview,
        "workflow_schema": workflow_schema,
        "audit_id": audit_id,
        "confirmation_required": True,
    }


async def _create_workflow_from_transcript(
    user_id: str,
    transcript: str,
    command_text: str,
    *,
    force_create: bool = False,
) -> dict:
    workflow, validation_errors = await _classify_workflow_request(user_id, transcript)
    trigger_phrase = workflow.get("trigger_phrase", "").strip()
    steps = workflow.get("steps", [])

    existing_workflow = await workflow_store.find_by_trigger(user_id, trigger_phrase)
    if existing_workflow and not force_create:
        logger.info("[audio/workflow] classifier trigger matched existing workflow trigger=%r user=%s",
                    trigger_phrase, user_id)
        return await _prepare_workflow_execution_confirmation(
            user_id=user_id,
            transcript=transcript,
            command_text=command_text,
            doc=existing_workflow,
        )
    if existing_workflow and force_create:
        logger.info(
            "[audio/workflow] explicit create request is overriding existing trigger=%r user=%s",
            trigger_phrase,
            user_id,
        )

    preview = _build_create_preview_from_schema(steps)
    workflow_schema = {
        "trigger_phrase": trigger_phrase,
        "steps": steps,
        "missing_params": workflow.get("missing_params", []),
        "confidence": workflow.get("confidence"),
        "validation_errors": validation_errors,
    }

    audit_id = await audit_store.create_audit_record(user_id, {
        "status": "awaiting_confirmation",
        "kind": "create",
        "transcript": transcript,
        "command_text": command_text,
        "workflow_trigger": trigger_phrase,
        "workflow_schema": workflow_schema,
        "preview": preview,
    })

    return await _queue_confirmation(
        user_id=user_id,
        kind="create",
        transcript=transcript,
        command_text=command_text,
        workflow_id="",
        workflow_trigger=trigger_phrase,
        steps=steps,
        preview=preview,
        workflow_schema=workflow_schema,
        audit_id=audit_id,
    )


async def _prepare_workflow_execution_confirmation(
    *,
    user_id: str,
    transcript: str,
    command_text: str,
    doc: dict,
) -> dict:
    workflow_id = str(doc.get("_id", ""))
    preview = await preview_workflow(user_id, doc["steps"])
    audit_id = await audit_store.create_audit_record(user_id, {
        "status": "awaiting_confirmation",
        "kind": "execute",
        "transcript": transcript,
        "command_text": command_text,
        "workflow_id": workflow_id,
        "workflow_trigger": doc.get("trigger_phrase", ""),
        "preview": preview,
    })

    if preview.get("status") == "blocked":
        await audit_store.update_audit_record(audit_id, {"status": "preview_failed"})
        return {
            "workflow_status": "failed",
            "workflow_message": _preview_failure_message(preview),
            "workflow_id": workflow_id,
            "workflow_trigger": doc.get("trigger_phrase", ""),
            "workflow_preview": preview,
            "audit_id": audit_id,
        }

    return await _queue_confirmation(
        user_id=user_id,
        kind="execute",
        transcript=transcript,
        command_text=command_text,
        workflow_id=workflow_id,
        workflow_trigger=doc.get("trigger_phrase", ""),
        steps=doc["steps"],
        preview=preview,
        workflow_schema={},
        audit_id=audit_id,
    )


def _build_result_message(result: dict) -> str:
    for step in result.get("steps_completed", []):
        label = step.get("step", "")
        r = step.get("result") or {}

        if "dominos.order_pizza" in label or "dominos.reorder_last" in label:
            price = r.get("price")
            placed = r.get("placed", False)
            store = r.get("storeID", "")
            price_str = f"${float(price):.2f}" if price else ""
            if placed and price_str:
                return f"Your pizza is on its way! Total is {price_str}. Order placed at store {store}."
            elif placed:
                return "Your pizza is on its way!"
            elif price_str:
                return f"Order priced at {price_str} but payment not processed. Add a card in the Domino's settings."
            else:
                return "Pizza order could not be placed. Check your payment info."

        if "slack" in label:
            return "Slack message sent."

        if "gmail" in label and "send" in label:
            return "Email sent."

        if "google_calendar" in label:
            return "Calendar event created."

        if "google_maps" in label:
            summary = r.get("summary") or r.get("directions") or ""
            return f"Directions ready. {summary}".strip()

    return "Done."


async def _execute_saved_workflow(doc: dict, user_id: str, audit_id: str = "") -> dict:
    workflow_id = str(doc.get("_id", ""))
    logger.info("[audio/workflow] executing id=%s trigger=%r user=%s",
                workflow_id, doc.get("trigger_phrase"), user_id)

    result = await execute_workflow(user_id, doc["steps"])
    workflow_status = "executed" if result["status"] == "success" else result["status"]
    workflow_message = _build_result_message(result) if result["status"] == "success" else result.get("message", "workflow failed")

    if audit_id:
        await audit_store.update_audit_record(audit_id, {
            "status": workflow_status,
            "workflow_result": result,
        })

    return {
        "workflow_status": workflow_status,
        "workflow_message": workflow_message,
        "workflow_id": workflow_id,
        "workflow_trigger": doc.get("trigger_phrase", ""),
        "workflow_result": result,
        "audit_id": audit_id,
    }


async def _confirm_pending_workflow(user_id: str, pending: confirmation_store.PendingConfirmation) -> dict:
    await audit_store.update_audit_record(pending.audit_id, {"status": "confirmed"})
    if pending.kind == "create":
        workflow_id = await workflow_store.save_workflow(
            user_id=user_id,
            trigger_phrase=pending.workflow_trigger,
            steps=pending.steps,
        )
        logger.info("[audio/workflow] created id=%s trigger=%r user=%s",
                    workflow_id, pending.workflow_trigger, user_id)
        await audit_store.update_audit_record(pending.audit_id, {
            "status": "created",
            "workflow_id": workflow_id,
        })
        return {
            "workflow_status": "created",
            "workflow_message": "workflow created",
            "workflow_id": workflow_id,
            "workflow_trigger": pending.workflow_trigger,
            "workflow_preview": pending.preview,
            "workflow_schema": pending.workflow_schema,
            "audit_id": pending.audit_id,
        }

    doc = {
        "_id": pending.workflow_id,
        "trigger_phrase": pending.workflow_trigger,
        "steps": pending.steps,
    }
    return await _execute_saved_workflow(doc, user_id, pending.audit_id)


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
        mime_type = "audio/wav"
    else:
        audio_bytes = audio_data
        filename = "audio.webm"
        mime_type = "audio/webm"

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

    if not transcript.strip():
        logger.info(f"[audio/end] ignoring empty transcript for chunk_id={chunk_id}")
        return JSONResponse({
            "chunk_id": chunk_id,
            "user_id": meta["user_id"],
            "transcript": "",
            "command": "",
            "action": "ignored",
            "agent_name": "",
            "workflow_status": "ignored",
            "workflow_message": "empty transcript ignored",
        })

    command = _extract_after_flux(transcript)

    # Keep the old action/agent classification code around for reference, but
    # route the audio flow through workflows only for now.
    #
    # action, agent_name = _classify_command(command)
    # logger.info(f"[audio/end] command={command!r} action={action} agent_name={agent_name!r}")
    action = "workflow"
    agent_name = ""
    logger.info(f"[audio/end] command={command!r} action={action} agent_name={agent_name!r}")

    workflow_response = None
    workflow_spoken_text = command.strip() or transcript.strip()
    if workflow_spoken_text:
        explicit_create_request = _is_explicit_workflow_creation_request(workflow_spoken_text)
        pending_confirmation = confirmation_store.get_pending(meta["user_id"])
        if pending_confirmation and _CONFIRM_RE.match(workflow_spoken_text):
            confirmation_store.pop_pending(meta["user_id"])
            workflow_response = await _confirm_pending_workflow(meta["user_id"], pending_confirmation)
            action = "workflow"
            agent_name = ""
        elif pending_confirmation and _DECLINE_RE.match(workflow_spoken_text):
            confirmation_store.pop_pending(meta["user_id"])
            await audit_store.update_audit_record(pending_confirmation.audit_id, {
                "status": "cancelled",
                "confirmation_utterance": workflow_spoken_text,
            })
            workflow_response = {
                "workflow_status": "cancelled",
                "workflow_message": "workflow cancelled",
                "workflow_id": pending_confirmation.workflow_id,
                "workflow_trigger": pending_confirmation.workflow_trigger,
                "audit_id": pending_confirmation.audit_id,
            }
            action = "workflow"
            agent_name = ""
        elif pending_confirmation:
            workflow_response = {
                "workflow_status": "awaiting_confirmation",
                "workflow_message": "please say yes or no",
                "workflow_id": pending_confirmation.workflow_id,
                "workflow_trigger": pending_confirmation.workflow_trigger,
                "workflow_preview": pending_confirmation.preview,
                "workflow_schema": pending_confirmation.workflow_schema,
                "audit_id": pending_confirmation.audit_id,
                "confirmation_required": True,
            }
            action = "workflow"
            agent_name = ""
        else:
            existing_workflow = None if explicit_create_request else await workflow_store.find_by_trigger(meta["user_id"], workflow_spoken_text)
            if existing_workflow:
                workflow_response = await _prepare_workflow_execution_confirmation(
                    user_id=meta["user_id"],
                    transcript=transcript,
                    command_text=workflow_spoken_text,
                    doc=existing_workflow,
                )
            else:
                workflow_response = await _create_workflow_from_transcript(
                    meta["user_id"],
                    workflow_spoken_text,
                    workflow_spoken_text,
                    force_create=explicit_create_request,
                )
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
    # 1. Classify with per-user app filtering
    logger.info("[workflow/create] classifying transcript=%r user=%s",
                payload.transcript, payload.user_id)
    try:
        workflow = await classify_for_user(payload.transcript, payload.user_id)
    except Exception as exc:
        logger.error("[workflow/create] classify failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Classification failed: {exc}")

    if workflow.get("intent") == "denied":
        reason = workflow.get("denial_reason", "None of your connected apps can handle that request.")
        raise HTTPException(status_code=422, detail={"intent": "denied", "reason": reason})

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


class DominosCredentialsRequest(BaseModel):
    firstName:      str
    lastName:       str = ""
    email:          str = ""
    phone:          str = ""
    address:        str
    cardNumber:     str = ""
    cardExpiration: str = ""
    cardCvv:        str = ""
    cardZip:        str = ""


@app.post("/user/{user_id}/credentials/dominos")
async def save_dominos_credentials(user_id: str, payload: DominosCredentialsRequest):
    """Save Domino's delivery info and optional payment card for a user."""
    data: dict = {
        "firstName": payload.firstName.strip(),
        "lastName":  payload.lastName.strip(),
        "email":     payload.email.strip(),
        "phone":     payload.phone.strip(),
        "address":   payload.address.strip(),
    }
    if payload.cardNumber.strip():
        data["card"] = {
            "number":     payload.cardNumber.strip(),
            "expiration": payload.cardExpiration.strip(),
            "cvv":        payload.cardCvv.strip(),
            "zip":        payload.cardZip.strip(),
        }
    await token_store.save_token(user_id, "dominos", data)
    logger.info("[credentials/dominos] saved user=%s has_card=%s", user_id, bool(payload.cardNumber))
    return {"status": "ok"}


@app.delete("/user/{user_id}/webhooks/{app}/{action}")
async def delete_user_webhook(user_id: str, app: str, action: str):
    """Remove a webhook for a specific app+action."""
    deleted = await zapier_store.delete_webhook(user_id, app, action)
    return {"deleted": deleted}


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT RUNNER ENDPOINTS  (/run page + preview + execute-stream)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/run", response_class=HTMLResponse)
async def run_page():
    """Serve the interactive workflow runner UI."""
    html_path = _BASE_DIR / "run_page.html"
    return HTMLResponse(html_path.read_text())


class WorkflowPreviewRequest(BaseModel):
    user_id: str
    prompt:  str


@app.post("/workflow/preview")
async def workflow_preview(payload: WorkflowPreviewRequest):
    """Classify a prompt → workflow JSON (no persistence). Used by /run page."""
    logger.info("[workflow/preview] user=%s prompt=%r", payload.user_id, payload.prompt)
    try:
        workflow = await classify_for_user(payload.prompt, payload.user_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Classification failed: {exc}")

    if workflow.get("intent") == "denied":
        reason = workflow.get("denial_reason", "None of your connected apps can handle that request.")
        return {
            "intent":         "denied",
            "denial_reason":  reason,
            "trigger_phrase": "",
            "steps":          [],
            "missing_params": [],
            "confidence":     0.0,
            "validation_errors": [],
        }

    errors = validate(workflow)
    return {
        "trigger_phrase":    workflow.get("trigger_phrase", ""),
        "steps":             workflow.get("steps", []),
        "missing_params":    workflow.get("missing_params", []),
        "confidence":        workflow.get("confidence"),
        "validation_errors": errors,
    }


class WorkflowExecuteStreamRequest(BaseModel):
    user_id: str
    steps:   list


@app.post("/workflow/execute-stream")
async def workflow_execute_stream(payload: WorkflowExecuteStreamRequest):
    """Execute workflow steps one-by-one, streaming SSE events per step."""
    import json

    async def event_stream():
        async for event in execute_workflow_stream(payload.user_id, payload.steps):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# OAUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

_CONNECTED_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#0f0f0f;color:#f0f0f0}}
.box{{text-align:center}}.check{{font-size:48px}}</style></head>
<body><div class="box"><div class="check">✓</div><h2>{service} connected</h2><p>You can close this tab.</p></div></body></html>"""


# ── Google ────────────────────────────────────────────────────────────────────

@app.get("/auth/google")
async def auth_google(user_id: str, request: Request):
    redirect_uri = _get_google_redirect_uri(request)
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         " ".join(_GOOGLE_SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",
        "state":         user_id,
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


async def _handle_google_callback(code: str, state: str, request: Request):
    """Shared logic for both Google callback paths."""
    user_id = state.strip()
    redirect_uri = _get_google_redirect_uri(request)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  redirect_uri,
                "grant_type":    "authorization_code",
            },
        )
    data = resp.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])

    token_payload = {
        "access_token":  data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "token_uri":     "https://oauth2.googleapis.com/token",
        "scopes":        _GOOGLE_SCOPES,
    }

    google_email = ""
    try:
        async with httpx.AsyncClient() as client:
            userinfo_resp = await client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {data['access_token']}"},
            )
        userinfo_resp.raise_for_status()
        google_email = str(userinfo_resp.json().get("email") or "").strip().lower()
    except Exception as exc:
        logger.warning("[auth/google] could not fetch userinfo for state=%s: %s", user_id, exc)

    token_user_ids = {user_id}
    if google_email:
        token_user_ids.add(google_email)

    for token_user_id in token_user_ids:
        await token_store.save_token(token_user_id, "google", token_payload)

    logger.info(
        "[auth/google] token saved state_user=%s google_email=%s aliases=%s",
        user_id,
        google_email or "(unknown)",
        sorted(token_user_ids),
    )
    connected_label = f"Google ({google_email})" if google_email else "Google"
    return HTMLResponse(_CONNECTED_HTML.format(service=connected_label))


@app.get("/connect/google/redirect")
async def auth_google_callback(code: str, state: str, request: Request):
    return await _handle_google_callback(code, state, request)


@app.get("/connect/google/redirect")
async def connect_google_redirect(code: str, state: str, request: Request):
    return await _handle_google_callback(code, state, request)


# ── Slack ─────────────────────────────────────────────────────────────────────

@app.get("/auth/slack")
async def auth_slack(user_id: str):
    params = {
        "client_id":    SLACK_CLIENT_ID,
        "scope":        "",
        "user_scope":   " ".join(_SLACK_USER_SCOPES),
        "redirect_uri": f"{BACKEND_URL}/connect/slack/redirect",
        "state":        user_id,
    }
    return RedirectResponse("https://slack.com/oauth/v2/authorize?" + urlencode(params))


@app.get("/connect/slack/redirect")
async def auth_slack_callback(code: str, state: str):
    user_id = state
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id":     SLACK_CLIENT_ID,
                "client_secret": SLACK_CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  f"{BACKEND_URL}/connect/slack/redirect",
            },
        )
    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(status_code=400, detail=data.get("error", "Slack OAuth failed"))

    user_token = data.get("authed_user", {}).get("access_token")
    await token_store.save_token(user_id, "slack", {
        "access_token": user_token,
        "team_id":      data.get("team", {}).get("id"),
    })
    logger.info("[auth/slack] token saved user=%s", user_id)
    return HTMLResponse(_CONNECTED_HTML.format(service="Slack"))


# ── Notion ────────────────────────────────────────────────────────────────────

@app.get("/auth/notion")
async def auth_notion(user_id: str):
    params = {
        "client_id":     NOTION_CLIENT_ID,
        "response_type": "code",
        "owner":         "user",
        "redirect_uri":  f"{BACKEND_URL}/connect/notion/authorize",
        "state":         user_id,
    }
    return RedirectResponse("https://api.notion.com/v1/oauth/authorize?" + urlencode(params))


@app.get("/connect/notion/authorize")
async def auth_notion_callback(code: str, state: str):
    user_id = state
    logger.info("[auth/notion] callback received user=%s code=%s", user_id, code[:8])
    credentials = base64.b64encode(f"{NOTION_CLIENT_ID}:{NOTION_CLIENT_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/oauth/token",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
            json={"grant_type": "authorization_code", "code": code},
        )
    data = resp.json()
    logger.info("[auth/notion] token response: %s", data)
    if "access_token" not in data:
        raise HTTPException(status_code=400, detail=data.get("error", "Notion OAuth failed"))

    await token_store.save_token(user_id, "notion", {
        "access_token": data["access_token"],
        "workspace_id": data.get("workspace_id"),
    })
    logger.info("[auth/notion] token saved user=%s", user_id)
    return HTMLResponse(_CONNECTED_HTML.format(service="Notion"))


# ── Notion Proxy for 3rd Party Integrations (e.g. Agentverse) ────────────────

@app.get("/notion/oauth/authorize")
async def notion_proxy_authorize(request: Request):
    """Proxy authorize URL for 3rd-party platforms."""
    params = dict(request.query_params)
    return RedirectResponse("https://api.notion.com/v1/oauth/authorize?" + urlencode(params))

@app.post("/notion/oauth/token")
async def notion_proxy_token(request: Request):
    """Proxy token URL that injects Notion's required Basic Auth header."""
    form = await request.form()
    data = dict(form)
    
    client_id = data.get("client_id", NOTION_CLIENT_ID)
    client_secret = data.get("client_secret", NOTION_CLIENT_SECRET)
    
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    
    payload = {
        "grant_type": data.get("grant_type", "authorization_code"),
        "code": data.get("code"),
        "redirect_uri": data.get("redirect_uri")
    }
    if "refresh_token" in data:
        payload["refresh_token"] = data["refresh_token"]
        
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.notion.com/v1/oauth/token",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
            json=payload,
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


# ── Connection status ─────────────────────────────────────────────────────────

@app.get("/user/{user_id}/connections")
async def get_connections(user_id: str):
    """Return which services the user has connected via OAuth."""
    services = await token_store.list_connections(user_id)
    return {"connected": services}


@app.get("/audit/{user_id}")
async def get_audit_trail(user_id: str):
    """Return recent workflow audit records for a user."""
    records = await audit_store.list_audit_records(user_id)
    return {"records": records}


if _ONBOARDING_DIR.exists():
    app.mount("/", StaticFiles(directory=_ONBOARDING_DIR, html=True), name="onboarding")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
