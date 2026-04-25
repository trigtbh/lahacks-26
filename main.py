import io
import os
import json
import struct
import uuid
import logging
import motor.motor_asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from openai import AsyncOpenAI
from elevenlabs.client import ElevenLabs

# Setup environment variables or default values
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "your_openrouter_api_key_here")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "your_elevenlabs_api_key_here")
MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")

# Configure OpenAI client for OpenRouter
client_llm = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# ElevenLabs client for STT
client_elevenlabs = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# MongoDB setup
client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = client.flow_db
workflows_collection = db.workflows

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

@app.get("/")
async def serve_index():
    return FileResponse("index.html")

from actions import PREDEFINED_ACTIONS

# Pydantic schema for Gemini Structured Output
class ActionSchema(BaseModel):
    app: str = Field(description="The application to perform the action on (e.g. gmail, calendar).")
    action: str = Field(description="The specific action to perform (e.g. send_email, create_event).")
    parameters: Dict[str, str] = Field(description="The resolved parameters for this action extracted from user input.")

class WorkflowSchema(BaseModel):
    trigger_phrase: str = Field(description="The natural language phrase that triggers this workflow.")
    apps: List[str] = Field(description="List of applications involved in the workflow.")
    actions: List[ActionSchema] = Field(description="List of actions to perform in order.")
    missing_parameters: List[str] = Field(description="List of required parameters that are missing and need to be asked for.")
    is_complete: bool = Field(description="True if all required parameters for all actions are provided, False otherwise.")
    suggested_question: str = Field(description="If is_complete is False, this is the voice prompt to ask the user for the missing parameters.")
    workflow_name: str = Field(description="A short, catchy name for this workflow (e.g. 'Morning Routine' or 'Send Email').")

# In-memory session store for chat histories
# In a production environment, this should be backed by Redis or a database.
sessions = {}

# Request and Response Models
class ParseRequest(BaseModel):
    user_input: str
    session_id: str

class ParseResponse(BaseModel):
    is_complete: bool
    reply_message: str
    workflow_id: Optional[str] = None
    workflow: Optional[dict] = None

@app.post("/parse", response_model=ParseResponse)
async def parse_intent(request: ParseRequest):
    session_id = request.session_id
    user_input = request.user_input

    # Initialize a new chat session if one doesn't exist
    if session_id not in sessions:
        system_instruction = f"""
        You are Flow, an AI assistant that converts user requests into executable workflows.
        You must ONLY use the following predefined applications and actions:
        {json.dumps(PREDEFINED_ACTIONS, indent=2)}

        Your goal is to extract:
        1. trigger phrase (the phrase that starts the workflow)
        2. app list (the apps involved)
        3. action steps (the sequence of actions to execute)
        4. required parameters (resolved parameters for the actions)

        If any required parameters are missing from the user's input based on the predefined actions, 
        you must set is_complete to false, list the missing parameters, and provide a suggested_question to ask the user for them.
        Once all required parameters are resolved, set is_complete to true.
        """
        
        # Append JSON schema instruction for OpenRouter
        system_instruction += f"\n\nRespond STRICTLY with a JSON object matching this schema:\n{json.dumps(WorkflowSchema.model_json_schema(), indent=2)}"
        
        sessions[session_id] = [
            {"role": "system", "content": system_instruction}
        ]

    sessions[session_id].append({"role": "user", "content": user_input})

    try:
        logger.info(f"Session {session_id} - User Input: {user_input}")
        logger.info(f"Session {session_id} - Sending request to OpenRouter (gemma-4-31b-it)")
        # Generate response using OpenRouter
        response = await client_llm.chat.completions.create(
            model="google/gemma-4-31b-it",
            messages=sessions[session_id],
            response_format={"type": "json_object"}
        )
        
        
        response_text = response.choices[0].message.content
        logger.info(f"Session {session_id} - Received response: {response_text}")
        sessions[session_id].append({"role": "assistant", "content": response_text})
        
        workflow_data = json.loads(response_text)
        logger.info(f"Session {session_id} - Parsed JSON: {workflow_data}")

        # Step 3: Loop if missing parameters
        if not workflow_data.get("is_complete"):
            return ParseResponse(
                is_complete=False,
                reply_message=workflow_data.get("suggested_question", "Can you provide more details?")
            )

        # Step 4: Embed trigger phrase (768-dim vector)
        trigger_phrase = workflow_data.get("trigger_phrase", user_input)
        
        # NOTE: OpenRouter does not provide embeddings natively. 
        # Mocking a 768-dim vector for now to maintain the schema.
        # If you need real embeddings, consider using OpenAI embeddings or a local sentence-transformers model.
        embedding = [0.0] * 768

        # Workflow written to MongoDB with resolved parameters and token refs
        document = {
            "trigger_phrase": trigger_phrase,
            "trigger_embedding": embedding,
            "workflow_name": workflow_data.get("workflow_name", "Custom Workflow"),
            "apps": workflow_data.get("apps", []),
            "actions": workflow_data.get("actions", []),
            "token_refs": [] # Placeholder for future token references
        }

        logger.info(f"Session {session_id} - Writing workflow to MongoDB: {document['workflow_name']}")
        result = await workflows_collection.insert_one(document)
        workflow_id = str(result.inserted_id)
        logger.info(f"Session {session_id} - Saved to MongoDB with ID {workflow_id}")

        # Clean up session since workflow is complete
        del sessions[session_id]

        # Step 5: Flow confirms aloud (returning message to be streamed)
        workflow_name = workflow_data.get("workflow_name", "new")
        reply_message = f"Saved as {workflow_name} workflow. Say confirm."

        if "_id" in document:
            document["_id"] = str(document["_id"])

        return ParseResponse(
            is_complete=True,
            reply_message=reply_message,
            workflow_id=workflow_id,
            workflow=document
        )

    except Exception as e:
        logger.error(f"Session {session_id} - Error parsing intent: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _build_wav(pcm_data: bytes, sample_rate: int, channels: int, bit_depth: int = 16) -> bytes:
    """Wrap raw PCM bytes in a minimal WAV (RIFF) container."""
    byte_rate = sample_rate * channels * (bit_depth // 8)
    block_align = channels * (bit_depth // 8)
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,       # total chunk size
        b"WAVE",
        b"fmt ",
        16,                   # PCM sub-chunk size
        1,                    # audio format (PCM)
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
    # --- Parse custom headers -----------------------------------------------
    sample_rate = int(request.headers.get("X-Audio-Sample-Rate", 16000))
    encoding    = request.headers.get("X-Audio-Encoding", "pcm_s16le").lower()
    channels    = int(request.headers.get("X-Audio-Channels", 1))
    user_id     = request.headers.get("X-User-Id", "unknown")

    logger.info(
        f"[transcribe] user={user_id} sample_rate={sample_rate} "
        f"encoding={encoding} channels={channels}"
    )

    # --- Buffer the entire body (end of body = end of transmission) ----------
    pcm_data = await request.body()
    if not pcm_data:
        raise HTTPException(status_code=400, detail="Empty audio body received.")

    logger.info(f"[transcribe] user={user_id} received {len(pcm_data)} bytes of PCM audio")

    # --- Build WAV container so ElevenLabs can parse the format --------------
    # Only pcm_s16le is currently supported; extend as needed.
    if encoding != "pcm_s16le":
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported encoding '{encoding}'. Only pcm_s16le is supported."
        )

    wav_bytes = _build_wav(pcm_data, sample_rate=sample_rate, channels=channels, bit_depth=16)

    # --- Send to ElevenLabs STT ----------------------------------------------
    try:
        wav_file = io.BytesIO(wav_bytes)
        wav_file.name = "audio.wav"  # SDK uses the name attribute to infer MIME type

        result = client_elevenlabs.speech_to_text.convert(
            file=wav_file,
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
