# Flux — Exhaustive Technical Reference

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Structure](#2-repository-structure)
3. [Technology Stack](#3-technology-stack)
4. [Backend Architecture](#4-backend-architecture)
5. [AI Pipeline](#5-ai-pipeline)
6. [Workflow Schema & Closed-World Model](#6-workflow-schema--closed-world-model)
7. [Execution Engine](#7-execution-engine)
8. [Param Resolver System](#8-param-resolver-system)
9. [Control Flow Engine](#9-control-flow-engine)
10. [Integration Reference](#10-integration-reference)
11. [Audio Pipeline](#11-audio-pipeline)
12. [AgentVerse Integration](#12-agentverse-integration)
13. [OAuth & Token Management](#13-oauth--token-management)
14. [Database Layer](#14-database-layer)
15. [API Endpoint Reference](#15-api-endpoint-reference)
16. [Mobile Client](#16-mobile-client)
17. [Onboarding Frontend](#17-onboarding-frontend)
18. [Domino's Wrapper Service](#18-dominos-wrapper-service)
19. [Deployment & Infrastructure](#19-deployment--infrastructure)
20. [Security Model](#20-security-model)
21. [Known Gaps & Future Work](#21-known-gaps--future-work)
22. [Environment Variable Reference](#22-environment-variable-reference)

---

## 1. System Overview

Flux is a voice-first automation engine. It accepts audio input, transcribes speech, classifies intent via an LLM, constructs validated workflow JSON from a closed-world action schema, optionally persists the workflow, and executes it against real cloud APIs — replying with synthesised speech.

The system is composed of four independent services:

| Service | Language | Role |
|---|---|---|
| `backend/` | Python 3.11, FastAPI | Core API, AI pipeline, executor |
| `mobile/` | Kotlin (Android) | Audio capture, wake word, transport |
| `onboarding/` | React 19, Vite | OAuth connection UI |
| `dominos_service/` | Node.js, Express | Domino's unofficial API wrapper |

---

## 2. Repository Structure

```
lahacks-26/
├── backend/
│   ├── main.py                      # FastAPI app, all route handlers (1683 lines)
│   ├── executor.py                  # Workflow step execution engine (1234 lines)
│   ├── agentverse_client.py         # AgentVerse discovery + ASI:ONE chat
│   ├── google_auth.py               # Google OAuth credential refresh helper
│   ├── google_people.py             # Google Contacts API wrapper
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── docker-compose.yml
│   │
│   ├── ai/
│   │   ├── classifier.py            # Stage 1: transcript → workflow JSON
│   │   ├── validator.py             # Stage 2: validate + repair workflow JSON
│   │   ├── llm.py                   # OpenRouter/Gemini client wrapper
│   │   ├── prompts.py               # All LLM system/user prompts
│   │   ├── environment.py           # ALLOWED_ACTIONS, INNATE_ACTIONS, CONTROL_ACTIONS
│   │   ├── app_resolver.py          # Per-user filtered system prompt builder
│   │   ├── condition_eval.py        # Safe AST evaluator for control flow conditions
│   │   └── infer_classifier.py      # Two-stage inference for complex tasks
│   │
│   ├── db.py                        # MongoDB Motor client
│   ├── token_store.py               # OAuth tokens per (user_id, service)
│   ├── workflow_store.py            # Workflow CRUD + fuzzy trigger matching
│   ├── audit_store.py               # Immutable execution audit trail
│   ├── confirmation_store.py        # Pending workflow confirmation state
│   ├── session_store.py             # Active AgentVerse session state (in-memory)
│   ├── zapier_store.py              # User-registered Zapier webhook URLs
│   │
│   ├── dominos_service/
│   │   ├── server.js
│   │   └── package.json
│   │
│   └── static/
│       ├── run_page.html            # Interactive workflow runner dev UI
│       └── infer_page.html          # Multi-step inference dev UI
│
├── mobile/
│   └── app/src/main/kotlin/
│       ├── FlowApplication.kt
│       ├── MainActivity.kt
│       ├── audio/
│       │   ├── AudioCaptureManager.kt
│       │   ├── AudioCaptureService.kt
│       │   ├── AudioRouteManager.kt
│       │   ├── WakeWordDetector.kt
│       │   └── RingBuffer.kt
│       └── network/
│           └── FlowApiClient.kt
│
└── onboarding/
    ├── package.json                  # React 19, Vite, Auth0
    └── src/
```

---

## 3. Technology Stack

### Backend
| Dependency | Version | Purpose |
|---|---|---|
| FastAPI | latest | HTTP API framework |
| uvicorn | latest | ASGI server |
| motor | latest | Async MongoDB driver |
| openai | latest | OpenRouter API client (pointed at openrouter.ai) |
| deepgram-sdk | latest | STT via Deepgram Nova-3 |
| elevenlabs | latest | TTS synthesis |
| google-auth / google-api-python-client | latest | Google OAuth + API access |
| httpx | latest | Async HTTP for Slack, Notion, SerpAPI |
| pydantic | v2 | Request/response validation |

### Frontend (Onboarding)
| Dependency | Version | Purpose |
|---|---|---|
| react | 19.2 | UI framework |
| vite | latest | Build tool |
| @auth0/auth0-react | latest | Auth0 integration |

### Mobile
| Technology | Purpose |
|---|---|
| Kotlin | Android app language |
| WebSocket | Audio chunk streaming |
| AudioRecord API | PCM 16-bit capture |

### AI/ML
| Service | Model | Purpose |
|---|---|---|
| OpenRouter | google/gemma-4-26b-a4b-it | Workflow classification, validation, dialogue |
| Deepgram | nova-3 | Speech-to-text |
| ElevenLabs | George (JBFqnCBsd6RMkjVDRZzb) | Text-to-speech |

---

## 4. Backend Architecture

### Request Lifecycle

```
Client Request
    │
    ▼
FastAPI Route Handler (main.py)
    │
    ├──[Audio]──▶ recording_store (in-memory bytes buffer)
    │              │
    │              ▼ (on /audio/end)
    │         Deepgram STT → transcript
    │              │
    │              ▼
    │         Intent Router
    │              │
    │    ┌─────────┼─────────┐
    │    ▼         ▼         ▼
    │  Agent    Workflow   Workflow
    │  Chat     Create     Execute
    │    │         │         │
    │    ▼         ▼         ▼
    │  Agentverse  Classifier Executor
    │  session     + Validator engine
    │              │         │
    │              ▼         ▼
    │            MongoDB   Cloud APIs
    │
    ▼
ElevenLabs TTS → base64 PCM audio → JSON response
```

### main.py Structure

`main.py` (1683 lines) contains all route handlers organized by functional domain:

- Lines 1–80: imports, FastAPI app init, CORS, static file mount
- Lines 80–300: audio endpoints (`/audio/*`)
- Lines 300–600: workflow management (`/workflow/*`)
- Lines 600–900: OAuth flows (`/auth/*`, `/connect/*`)
- Lines 900–1100: user management (connections, webhooks, credentials)
- Lines 1100–1400: agent routing (`/agent/chat`)
- Lines 1400–1600: multi-step inference (`/infer/*`)
- Lines 1600–1683: audit trail (`/audit/*`)

---

## 5. AI Pipeline

### Overview

The AI pipeline converts a raw transcript into a validated, executable workflow JSON. It is a three-stage pipeline:

```
transcript
    │
    ▼
Stage 1: Classifier
    │   Model: Gemma-4-26B
    │   Prompt: CLASSIFIER_SYSTEM (filtered for user's connected apps)
    │   Output: {intent, trigger_phrase, steps[], missing_params[], confidence}
    │
    ▼
Stage 2: Validator
    │   Checks every step against ALLOWED_ACTIONS schema
    │   Identifies: unknown_apps, invalid_actions, missing_required_params, invalid_param_types
    │
    ▼
Stage 3: Repair (conditional, up to 2 retries)
    │   Model: Gemma-4-26B
    │   Prompt: VALIDATOR_SYSTEM + error list
    │   Output: corrected workflow JSON
    │
    ▼
Final workflow JSON (or error if repair fails)
```

### `ai/llm.py` — LLM Client

```python
async def generate_json(system: str, user: str) -> dict
async def generate_text(system: str, user: str) -> str
```

- Uses `openai.AsyncOpenAI` with `base_url="https://openrouter.ai/api/v1"`
- Default model: `google/gemma-4-26b-a4b-it` (overridable via `LLM_MODEL` env)
- Strips markdown code fences from response before JSON parsing
- Handles array vs. object responses (coerces to expected type)

### `ai/classifier.py` — Workflow Classifier

Entry point: `classify_for_user(transcript: str, user_id: str) -> ClassificationResult`

Steps:
1. Build filtered system prompt via `app_resolver.build_filtered_system_prompt(user_id)`
2. Call `generate_json(system, transcript)`
3. Parse and validate the JSON shape
4. Return `ClassificationResult` dataclass

`ClassificationResult` fields:
- `intent`: `"create_workflow" | "trigger_workflow" | "other" | "denied"`
- `trigger_phrase`: normalized string
- `steps`: list of step dicts
- `missing_params`: list of param names the model couldn't fill
- `confidence`: float 0–1

### `ai/validator.py` — Schema Validator + Repair

Entry point: `validate_and_repair(workflow: dict) -> dict`

Validation checks per step:
1. `app` is in `ALLOWED_ACTIONS` or `INNATE_ACTIONS` or `CONTROL_ACTIONS`
2. `action` is valid for that app
3. Required params are present
4. Param values match declared types (string, list, dict)

If errors found:
- Constructs error summary string
- Calls `generate_json(VALIDATOR_SYSTEM, error_summary + original_json)`
- Retries up to 2 times
- Raises `ValidationError` if still failing after retries

### `ai/prompts.py` — Prompt Definitions

| Prompt Constant | Used By | Purpose |
|---|---|---|
| `CLASSIFIER_SYSTEM` | classifier.py | Full environment spec for workflow generation |
| `VALIDATOR_SYSTEM` | validator.py | JSON repair instructions |
| `DIALOGUE_SYSTEM` | main.py | Ask user for missing params |
| `TRIGGER_SYSTEM` | workflow_store.py | Fuzzy trigger phrase matching |
| `EXECUTOR_SYSTEM` | executor.py | Summarize step results in natural language |
| `_ANALYSIS_SYSTEM` | infer_classifier.py | Stage 1 — check if task needs 3rd-party APIs |
| `_PLAN_SYSTEM` | infer_classifier.py | Stage 2 — break task into API call substeps |

### `ai/infer_classifier.py` — Two-Stage Inference

For complex multi-step tasks that don't map cleanly to a single workflow.

**Stage 1 (Analysis):**
- Prompt: `_ANALYSIS_SYSTEM`
- Input: user query + user's connected integrations
- Output: `{needs_external: bool, required_integrations: [], missing_integrations: [], analysis: str}`

**Stage 2 (Planning):**
- Prompt: `_PLAN_SYSTEM`
- Input: user query + stage 1 analysis
- Output: `{substeps: [{title, description, api_endpoint, params, expected_output}]}`

**Clarification loop:**
- If stage 1 identifies missing information, returns clarification questions
- `/infer/clarify` endpoint accepts answers and re-runs stage 2 with enriched context

---

## 6. Workflow Schema & Closed-World Model

### `ai/environment.py` — Action Registry

The closed-world model prevents hallucinated actions by restricting the classifier to an explicit list of valid apps, actions, and parameter schemas.

#### ALLOWED_ACTIONS Structure

```python
ALLOWED_ACTIONS = {
    "app_name": {
        "action_name": {
            "description": str,
            "params": {
                "param_name": {
                    "type": "string" | "list" | "dict" | "boolean" | "integer",
                    "required": bool,
                    "description": str,
                    "resolver": bool  # if True, value can be a resolver expression
                }
            }
        }
    }
}
```

#### Registered Apps (ALLOWED_ACTIONS)

| App Key | Actions |
|---|---|
| `gmail` | `send`, `draft`, `search` |
| `google_calendar` | `create_event`, `update_event`, `cancel_event` |
| `slack` | `send_dm`, `send_channel`, `get_channels` |
| `notion` | `create_page`, `append_blocks`, `get_page_link` |
| `google_drive` | `read_file`, `create_file`, `search_files`, `share_file` |
| `google_flights` | `search_flights` |
| `google_maps` | `get_directions`, `search_nearby` |
| `google_people` | `list_contacts`, `search_contacts` |
| `dominos` | `order_pizza`, `reorder_last` |
| `agentverse` | `chat` |
| `github` | (stubbed — no executor handler) |
| `spotify` | (stubbed — no executor handler) |
| `uber` | (stubbed — no executor handler) |

#### INNATE_ACTIONS (no external API required)

| Action | Description |
|---|---|
| `get_datetime` | Current date/time in specified format |
| `calculate` | Arithmetic expression evaluation |
| `format_text` | String interpolation with context refs |
| `http_request` | Generic HTTP call |
| `wait` | Sleep N seconds |
| `set_variable` | Write to context dict |
| `get_variable` | Read from context dict |
| `log` | Debug log to execution trace |
| `assert` | Raise if condition false |
| `return` | Early exit with value |
| `noop` | No-op placeholder |
| `send_notification` | OS/push notification |
| `append_to_list` | Mutate a context list |
| `merge_dicts` | Combine two context dicts |

#### CONTROL_ACTIONS

| Action | Description |
|---|---|
| `control.if` | Conditional branch |
| `control.while` | Loop until condition false |
| `control.for_each` | Iterate over list |

### `ai/app_resolver.py` — Per-User Filtered Prompts

`build_filtered_system_prompt(user_id: str) -> str`

1. Queries `token_store` for all OAuth tokens for `user_id`
2. Maps tokens to app keys: Google token → `gmail`, `google_calendar`, `google_drive`, `google_maps`, `google_flights`, `google_people`
3. Fetches Zapier webhooks from `zapier_store` — adds custom app entries
4. Builds a reduced `ALLOWED_ACTIONS` dict containing only available apps
5. Serializes to a compact JSON block embedded in `CLASSIFIER_SYSTEM`

This means the LLM never sees apps the user hasn't connected — eliminating a class of hallucination.

---

## 7. Execution Engine

### `executor.py` — Step Dispatcher

Entry points:
- `execute_workflow(workflow: dict, user_id: str) -> ExecutionResult` — blocking
- `execute_workflow_stream(workflow: dict, user_id: str) -> AsyncGenerator[str, None]` — SSE

**Execution loop:**

```python
context = {}  # shared mutable context across steps
for step in workflow["steps"]:
    params = resolve_params(step["params"], context, user_id)
    result = await dispatch_step(step["app"], step["action"], params, user_id)
    context[step.get("output_key", f"step_{i}")] = result
    yield sse_event(step, result)
```

### Step Dispatch Table

```
app="gmail"          → gmail_send / gmail_draft / gmail_search
app="google_calendar" → gcal_create / gcal_update / gcal_cancel
app="slack"          → slack_dm / slack_channel / slack_channels
app="notion"         → notion_create / notion_append / notion_link
app="google_drive"   → drive_read / drive_create / drive_search / drive_share
app="google_flights" → flights_search (SerpAPI)
app="google_maps"    → maps_directions / maps_nearby
app="google_people"  → people_list / people_search
app="dominos"        → dominos_order / dominos_reorder
app="agentverse"     → agentverse_chat
app="zapier.*"       → zapier_webhook_call
innate.*             → innate_executor (local computation)
control.*            → control_flow_handler (recursive)
```

### Token Injection

For each OAuth-backed step, executor fetches credentials from `token_store`:
```python
creds = await token_store.get_token(user_id, "google")
if creds and creds.expired:
    creds = await google_auth.refresh(creds)
    await token_store.set_token(user_id, "google", creds)
```

On 401 from Google APIs, raises `TokenExpiredError` — caught at route level, prompts user to re-authenticate.

### SSE Streaming Format

`/workflow/execute-stream` yields newline-delimited JSON events:
```
data: {"type":"step_start","step":{"app":"gmail","action":"send"}}\n\n
data: {"type":"step_complete","step":...,"result":{"status":"ok","message_id":"..."}}\n\n
data: {"type":"step_error","step":...,"error":"TokenExpiredError"}\n\n
data: {"type":"workflow_complete","steps_completed":3,"steps_failed":0}\n\n
```

---

## 8. Param Resolver System

Params can contain special resolver expressions that are evaluated at execution time (not classification time). This allows workflows saved today to use fresh data tomorrow.

### Resolver Syntax

| Expression | Resolved To |
|---|---|
| `time.now` | ISO 8601 datetime string |
| `time.now+30m` / `time.now-1h` | Datetime ± offset (m/h/d) |
| `time.today_at:HH:MM` | Today's date at specified time |
| `time.tomorrow` | Tomorrow's date |
| `calendar.next_event` | Full next event object |
| `calendar.next_event.title` | Title of next event |
| `calendar.next_event.start_time` | Start datetime |
| `calendar.next_event.location` | Location field |
| `calendar.next_event.attendees` | List of attendee emails |
| `user.contacts.email:Name` | Email of contact "Name" via Google Contacts |
| `user.contacts.by_name:Name` | Full contact record for "Name" |
| `google_drive.file_by_name:filename` | Drive file ID matching filename |
| `google_drive.latest_file` | Most recently modified Drive file |
| `google_maps.directions_to_next_event` | Directions to next calendar event location |
| `context.{key}` | Output of a previous step |
| `context.{key}.{field}` | Field within a previous step's output |

### Resolution Logic (`executor.py: resolve_params`)

```python
def resolve_param_value(value: str, context: dict, user_id: str) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith("time."):
        return resolve_time(value)
    if value.startswith("calendar.next_event"):
        return resolve_calendar(value, user_id)
    if value.startswith("user.contacts."):
        return resolve_contacts(value, user_id)
    if value.startswith("google_drive."):
        return resolve_drive(value, user_id)
    if value.startswith("google_maps."):
        return resolve_maps(value, user_id)
    if value.startswith("context."):
        key_path = value[8:].split(".")
        return deep_get(context, key_path)
    return value  # static string
```

Resolver functions are async and make real API calls where needed (Calendar, Drive, Maps, Contacts).

---

## 9. Control Flow Engine

### `ai/condition_eval.py` — Safe Expression Evaluator

Control flow conditions are evaluated using a whitelist AST visitor — not `eval()` — preventing code injection.

**Allowed AST node types:**
- `Expression`, `BoolOp` (and/or), `Compare`, `UnaryOp` (not)
- `Name` (variable lookup), `Constant` (string/int/bool/None)
- `Call` (whitelist: `len`, `str`, `int`, `float`, `bool`, `list`, `dict`, `isinstance`, `in`, `not in`)
- `Attribute` (string/list methods: `.lower()`, `.upper()`, `.startswith()`, `.endswith()`, `.strip()`, `.split()`, `.join()`, `.get()`)
- `Subscript` (dict/list index)

**Context injection:** condition strings may reference `context.{key}` which is substituted before evaluation.

### `control.if` Schema

```json
{
  "app": "control",
  "action": "if",
  "params": {
    "condition": "context.email_sent == true",
    "then": [ ...steps... ],
    "else": [ ...steps... ]
  }
}
```

### `control.while` Schema

```json
{
  "app": "control",
  "action": "while",
  "params": {
    "condition": "context.retry_count < 3",
    "steps": [ ...steps... ],
    "max_iterations": 100
  }
}
```

`max_iterations` defaults to 100, hard-capped at 100.

### `control.for_each` Schema

```json
{
  "app": "control",
  "action": "for_each",
  "params": {
    "items": "context.attendees",
    "loop_variable": "attendee",
    "steps": [ ...steps... ]
  }
}
```

`items` must resolve to a list. Each iteration binds `loop_variable` into context.

---

## 10. Integration Reference

### Gmail (`google` OAuth token)

| Action | Key Params | Notes |
|---|---|---|
| `send` | `to`, `subject`, `body`, `cc?`, `bcc?` | Sends immediately |
| `draft` | `to`, `subject`, `body` | Creates draft, returns `draft_id` |
| `search` | `query`, `max_results?` | Returns list of message summaries |

Uses `googleapiclient.discovery.build("gmail", "v1")`.

### Google Calendar (`google` OAuth token)

| Action | Key Params | Notes |
|---|---|---|
| `create_event` | `title`, `start`, `end`, `description?`, `location?`, `attendees?` | Returns `event_id` |
| `update_event` | `event_id`, `start?`, `end?`, `title?` | Partial update |
| `cancel_event` | `event_id` | Sets status to "cancelled" |

`start`/`end` accept ISO 8601 strings or resolver expressions.

### Slack (`slack` OAuth token)

| Action | Key Params | Notes |
|---|---|---|
| `send_dm` | `user`, `text` | `user` = display name or user ID |
| `send_channel` | `channel`, `text` | `channel` = name or ID |
| `get_channels` | — | Returns list of `{id, name}` |

Uses `httpx` against `https://slack.com/api/`.

User lookup for DM: calls `users.list`, filters by `display_name` or `real_name`.

### Notion (`notion` OAuth token)

| Action | Key Params | Notes |
|---|---|---|
| `create_page` | `parent_id`, `title`, `content?` | Returns `page_id`, `url` |
| `append_blocks` | `page_id`, `blocks` | Appends rich-text blocks |
| `get_page_link` | `page_id?`, `title?` | Returns shareable URL |

Uses Notion API v1 (`https://api.notion.com/v1/`). `parent_id` can be a database ID or page ID.

### Google Drive (`google` OAuth token)

| Action | Key Params | Notes |
|---|---|---|
| `read_file` | `file_id` | Returns text content (exports Docs to plain text) |
| `create_file` | `name`, `content`, `parent_id?` | Creates file, returns `file_id` |
| `search_files` | `query` | Returns list of `{id, name, mimeType}` |
| `share_file` | `file_id`, `email`, `role?` | Default role: `reader` |

### Google Flights (SerpAPI)

| Action | Key Params | Notes |
|---|---|---|
| `search_flights` | `origin`, `destination`, `date`, `return_date?`, `adults?` | Returns top-N flight options |

Calls `https://serpapi.com/search` with `engine=google_flights`.

### Google Maps (Google Maps API key)

| Action | Key Params | Notes |
|---|---|---|
| `get_directions` | `origin`, `destination`, `mode?` | Returns route summary, duration, distance |
| `search_nearby` | `location`, `type`, `radius?` | Returns list of places |

`mode` defaults to `driving`. Supports `driving`, `walking`, `bicycling`, `transit`.

### Google Contacts / People

| Action | Key Params | Notes |
|---|---|---|
| `list_contacts` | `max_results?` | Returns all contacts |
| `search_contacts` | `query` | Returns matching contacts |

Uses `googleapiclient.discovery.build("people", "v1")`.

### Domino's (Node.js wrapper)

| Action | Key Params | Notes |
|---|---|---|
| `order_pizza` | `size`, `crust`, `toppings`, `address?` | Calls dominos npm; uses stored address if omitted |
| `reorder_last` | — | Re-submits last stored order |

Routes to `DOMINOS_SERVICE_URL` (default `http://dominos:3001`).

Address and payment card are stored in `token_store` under key `dominos` per user.

### AgentVerse (`agentverse` API key)

| Action | Key Params | Notes |
|---|---|---|
| `chat` | `agent_name`, `message` | Searches for agent, sends message, returns reply |

1. `GET /api/v1/agents?name=X` — agent discovery
2. `POST https://api.asi1.ai/v1/chat/completions` — ASI:ONE chat completions
3. Session maintained in `session_store` (in-memory dict keyed by `user_id`)

---

## 11. Audio Pipeline

### Android → Backend Flow

```
AudioRecord (PCM 16-bit, 16kHz, mono)
    │
    ▼
WakeWordDetector
    │  Detects "Hey Flux" using on-device keyword model
    │  Starts recording after wake word
    │
    ▼
AudioCaptureManager
    │  Buffers audio in RingBuffer
    │  Detects silence (VAD) to auto-stop
    │
    ▼
FlowApiClient
    ├── POST /audio/start   {chunk_id: uuid, user_id: str}
    ├── POST /audio/stream  (binary body = PCM chunk)
    │     ↑ repeated N times
    └── POST /audio/end     {chunk_id: uuid, user_id: str}
```

### Backend Audio Processing

1. `/audio/start`: allocates `recording_store[chunk_id] = []`
2. `/audio/stream`: appends raw bytes to list
3. `/audio/end`:
   - Concatenates all chunks → single bytes object
   - Calls Deepgram Nova-3 async transcription
   - Extracts transcript text
   - Strips wake word prefix (everything before first comma or after "Hey Flux,")
   - Routes to intent handler

### Audio Response

All text replies are synthesised via ElevenLabs before returning:
```python
audio_bytes = await elevenlabs_client.generate(
    text=reply_text,
    voice=ELEVENLABS_VOICE_ID,
    model="eleven_turbo_v2"
)
audio_b64 = base64.b64encode(audio_bytes).decode()
```

Returns:
```json
{
  "action": "create_workflow | trigger_workflow | agent_chat | other",
  "transcript": "...",
  "reply": "...",
  "audio": "<base64 PCM>",
  "workflow": {...}
}
```

---

## 12. AgentVerse Integration

### `agentverse_client.py`

**Agent Discovery:**
```python
GET https://agentverse.ai/api/v1/agents?name={query}
Headers: Authorization: Bearer {AGENTVERSE_API_KEY}
```

Returns list of agents with `address`, `name`, `description`.

**Agent Chat:**
```python
POST https://api.asi1.ai/v1/chat/completions
Headers: Authorization: Bearer {AGENTVERSE_API_KEY}
Body: {
  "model": "asi1-mini",
  "messages": [...history...],
  "agent": {agent_address},
  "session_id": {user_id}
}
```

### Session Management

`session_store.py` (in-memory):
```python
_sessions: dict[str, dict] = {}
# key: user_id
# value: {agent_address, agent_name, messages: [...]}
```

Sessions survive request boundaries within a server process but are lost on restart (TODO: Redis).

### Intent Routing for Agent Chat

When transcript contains "talk to X" or "ask X" pattern:
1. Extract agent name X
2. Search AgentVerse for matching agent
3. If session already active for `user_id`, continue conversation
4. Otherwise, start new session with found agent
5. Forward user message, stream reply back

---

## 13. OAuth & Token Management

### `token_store.py`

MongoDB collection: `tokens`
Document schema:
```json
{
  "user_id": "string",
  "service": "google | slack | notion | dominos",
  "token_data": { ... },
  "updated_at": "ISODate"
}
```

API:
```python
await token_store.get_token(user_id: str, service: str) -> dict | None
await token_store.set_token(user_id: str, service: str, token_data: dict) -> None
await token_store.delete_token(user_id: str, service: str) -> None
await token_store.list_services(user_id: str) -> list[str]
```

### Google OAuth Flow

1. `GET /auth/google?user_id=X` — generates Google OAuth URL with `state=user_id`
2. User authorizes → Google redirects to `GET /connect/google/redirect?code=...&state=user_id`
3. Backend exchanges code for tokens (access + refresh)
4. Stores in `token_store` under `(user_id, "google")`

**Refresh:** `google_auth.py` wraps `google.oauth2.credentials.Credentials.refresh(Request())`.
On expiry, executor catches `HttpError 401`, refreshes, retries once.

### Slack OAuth Flow

1. `GET /auth/slack?user_id=X` — Slack OAuth URL (scopes: `chat:write`, `users:read`, `channels:read`)
2. Redirect → `GET /connect/slack/redirect?code=...&state=user_id`
3. Exchange for `access_token`, store under `(user_id, "slack")`

### Notion OAuth Flow

1. `GET /auth/notion?user_id=X` — Notion OAuth URL
2. Redirect → `GET /connect/notion/authorize?code=...&state=user_id`
3. Exchange for `access_token`, store under `(user_id, "notion")`

Note: Also exposes `/notion/oauth/authorize` and `/notion/oauth/token` as proxies for third-party Notion integration scenarios.

---

## 14. Database Layer

### MongoDB Collections

All accessed via Motor async driver (`db.py`).

| Collection | Purpose | Key Fields |
|---|---|---|
| `tokens` | OAuth credentials | `user_id`, `service`, `token_data` |
| `workflows` | Saved user workflows | `user_id`, `trigger_phrase`, `steps`, `created_at` |
| `audit` | Execution history | `user_id`, `workflow_id`, `status`, `steps_completed`, `timestamp` |
| `confirmations` | Pending confirmations | `user_id`, `workflow`, `expires_at` |
| `zapier_webhooks` | Custom app webhooks | `user_id`, `app`, `action`, `webhook_url` |

### `workflow_store.py` — Trigger Matching

`match_trigger(transcript: str, user_id: str) -> dict | None`

1. Normalize transcript (lowercase, expand contractions, strip punctuation)
2. Exact match against stored `trigger_phrase` values
3. Substring match (transcript contains trigger or vice versa)
4. LLM fuzzy match: `generate_text(TRIGGER_SYSTEM, transcript + all_trigger_phrases)`
   - Model selects closest match or returns "NO_MATCH"
5. Returns matched workflow dict or `None`

### `confirmation_store.py`

Pending confirmations expire after 60 seconds. On `/audio/end`, if confirmation is pending for `user_id`:
- Check if transcript is affirmative ("yes", "yeah", "do it", "confirm", etc.)
- If yes: retrieve pending workflow, execute it
- If no: cancel and discard

---

## 15. API Endpoint Reference

### Audio

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/audio/start` | `{chunk_id, user_id}` | `{status: "ok"}` |
| POST | `/audio/stream` | binary bytes | `{status: "ok"}` |
| POST | `/audio/end` | `{chunk_id, user_id}` | `{action, transcript, reply, audio, workflow?}` |

### Workflow

| Method | Path | Body / Params | Response |
|---|---|---|---|
| POST | `/workflow/create` | `{transcript, user_id}` | `{workflow_id, workflow}` |
| POST | `/workflow/seed` | `{workflows: [...], user_id}` | `{inserted: N}` |
| GET | `/workflow/list/{user_id}` | — | `[...workflow objects...]` |
| POST | `/workflow/trigger` | `{transcript, user_id}` | `{matched, workflow?, result?}` |
| DELETE | `/workflow/{workflow_id}` | — | `{deleted: true}` |
| POST | `/workflow/execute` | `{text, user_id}` | `{action, reply, audio, result?}` |
| POST | `/workflow/preview` | `{transcript, user_id}` | `{workflow}` (no save) |
| POST | `/workflow/execute-stream` | `{workflow, user_id}` | `text/event-stream` |

### Agent

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/agent/chat` | `{message, user_id, agent_name?}` | `{reply, agent_name}` |

### Infer

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/infer/query` | `{query, user_id}` | `{analysis, substeps?, clarification_needed?, questions?}` |
| POST | `/infer/clarify` | `{query, user_id, answers}` | `{substeps}` |
| GET | `/infer` | — | HTML page |

### Auth / OAuth

| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/auth/google` | `user_id` | redirect to Google |
| GET | `/connect/google/redirect` | `code`, `state` | redirect to onboarding |
| GET | `/auth/slack` | `user_id` | redirect to Slack |
| GET | `/connect/slack/redirect` | `code`, `state` | redirect to onboarding |
| GET | `/auth/notion` | `user_id` | redirect to Notion |
| GET | `/connect/notion/authorize` | `code`, `state` | redirect to onboarding |

### User Management

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/user/{user_id}/connections` | — | `{services: [...]}` |
| POST | `/user/{user_id}/webhooks` | `{app, action, webhook_url}` | `{ok: true}` |
| GET | `/user/{user_id}/webhooks` | — | `[...webhook objects...]` |
| DELETE | `/user/{user_id}/webhooks/{app}/{action}` | — | `{deleted: true}` |
| POST | `/user/{user_id}/credentials/dominos` | `{address, card}` | `{ok: true}` |

### Audit

| Method | Path | Response |
|---|---|---|
| GET | `/audit/{user_id}` | `[...audit records...]` |

---

## 16. Mobile Client

### Key Files

**`MainActivity.kt`**
- Entry point; manages permissions (RECORD_AUDIO, FOREGROUND_SERVICE)
- Initializes `AudioCaptureManager`, `WakeWordDetector`, `FlowApiClient`
- Displays conversation transcript and reply text

**`AudioCaptureManager.kt`**
- Opens `AudioRecord` with `ENCODING_PCM_16BIT`, 16kHz, mono
- Implements silence detection (VAD): if RMS < threshold for 1.5s, stops
- Buffers to `RingBuffer` to drop stale pre-wake audio

**`WakeWordDetector.kt`**
- On-device detection of configurable wake phrase
- Triggers `AudioCaptureManager.startCapture()`

**`FlowApiClient.kt`**
- Constructs multipart form for `/audio/stream` chunks
- Sends chunks in 4KB blocks
- Parses JSON response, decodes base64 audio, plays via `AudioTrack`

**`AudioRouteManager.kt`**
- Manages audio focus, speaker/earpiece routing
- Ensures TTS plays through appropriate output

**`RingBuffer.kt`**
- Fixed-size circular buffer for pre-wake audio retention
- Configurable capacity (default: 2s of audio at 16kHz)

---

## 17. Onboarding Frontend

**Stack:** React 19.2, Vite, Auth0

**Purpose:** Guide users through connecting their apps (Google, Slack, Notion). Presents OAuth connect buttons that deep-link to backend `/auth/*` endpoints.

**Auth0 integration:** Uses `@auth0/auth0-react` for the user's Flux account identity. The Auth0 `sub` claim becomes the `user_id` passed to all backend calls.

**State:** After OAuth round-trips, backend stores tokens in MongoDB. Frontend confirms connection by calling `GET /user/{user_id}/connections`.

---

## 18. Domino's Wrapper Service

### `dominos_service/server.js`

Express server wrapping the unofficial `dominos` npm package.

**Endpoints:**

`POST /order`
```json
{
  "address": {"street": "...", "city": "...", "zip": "..."},
  "card": {"number": "...", "expiration": "...", "cvv": "...", "zip": "..."},
  "items": [{"code": "12SCREEN", "options": {...}}]
}
```

`POST /reorder`
```json
{"order_id": "..."}
```

`GET /stores`
```json
{"address": {...}}
```

**Flow:**
1. Find nearest store via `dominos.NearbyStores(address)`
2. Validate order: `store.validateOrder(order)`
3. Price order: `store.priceOrder(order)`
4. Place order: `store.placeOrder(order, card)` — charges real card

Backend Python calls this service via `httpx` at `DOMINOS_SERVICE_URL`.

---

## 19. Deployment & Infrastructure

### Docker Compose (`backend/docker-compose.yml`)

```yaml
services:
  web:
    build: .
    ports: ["8000:8000"]
    volumes: [".:/app"]
    env_file: .env
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
    networks: [proxy]

  dominos:
    build: ./dominos_service
    ports: ["3001:3001"]
    networks: [proxy]

networks:
  proxy:
    external: true
```

The `proxy` network must be pre-created (`docker network create proxy`).

### `backend/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Static File Serving

The FastAPI app mounts the built onboarding React app at `/`:
```python
app.mount("/", StaticFiles(directory="static/onboarding_dist", html=True), name="static")
```

Dev UI pages (`/run`, `/infer`) are served from `static/` directory.

---

## 20. Security Model

### Authentication

- **User identity:** Auth0 JWT (managed by onboarding frontend)
- **API endpoints:** No bearer token validation — `user_id` is passed as a plain string parameter
  - **Risk:** Any caller knowing a `user_id` can trigger workflows on that user's behalf
- **OAuth state:** Uses `user_id` as OAuth `state` param — CSRF risk on OAuth callbacks

### Token Storage

- Google, Slack, Notion OAuth tokens stored in MongoDB in plaintext
- Domino's card details stored in MongoDB — PCI-DSS non-compliant
- No encryption at rest beyond what MongoDB Atlas may provide

### Code Execution Safety

- `condition_eval.py` uses AST whitelist — prevents arbitrary code injection in control flow conditions
- Closed-world action schema prevents hallucinated API calls
- No `eval()` or `exec()` in hot paths

### Input Validation

- Pydantic models on request bodies
- No SQL injection risk (MongoDB + Motor)
- No XSS risk (API-only, no HTML templates rendering user content)

### Exposed Secrets

The committed `.env` file contains live credentials for all services. These should be rotated immediately for production use.

---

## 21. Known Gaps & Future Work

### Architecture Gaps

| Gap | Impact | Recommended Fix |
|---|---|---|
| In-memory session state (`session_store`) | Lost on restart, not multi-process safe | Redis |
| No API authentication | Any caller can act as any user | Auth0 JWT validation middleware |
| OAuth state CSRF | Session fixation possible | Signed state tokens |
| Domino's card in plaintext MongoDB | PCI-DSS violation | Stripe for payment handling |
| Single-process audio buffer | Not horizontally scalable | Redis or S3 for chunk storage |
| No rate limiting | Abuse / cost risk | FastAPI `slowapi` or API gateway |

### Stubbed Integrations

- **GitHub** — defined in `ALLOWED_ACTIONS`, no executor handlers
- **Spotify** — defined in `ALLOWED_ACTIONS`, no executor handlers
- **Uber** — defined in `ALLOWED_ACTIONS`, no executor handlers

### Missing Features

- Workflow editing after creation
- Workflow scheduling (cron-based triggers, not just phrase triggers)
- Multi-turn dialogue for missing params during classification
- Persistent audit analytics / dashboard
- iOS mobile client

---

## 22. Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key for Gemma-4 access |
| `LLM_MODEL` | No | `google/gemma-4-26b-a4b-it` | Model string passed to OpenRouter |
| `DEEPGRAM_API_KEY` | Yes | — | Deepgram STT key |
| `ELEVENLABS_API_KEY` | Yes | — | ElevenLabs TTS key |
| `ELEVENLABS_VOICE_ID` | No | `JBFqnCBsd6RMkjVDRZzb` | ElevenLabs voice ID (default: George) |
| `GOOGLE_CLIENT_ID` | Yes | — | Google OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | — | Google OAuth 2.0 client secret |
| `BACKEND_URL` | Yes | — | Public URL of backend (e.g. `https://flux.example.com`) |
| `GOOGLE_REDIRECT_URI` | No | `{BACKEND_URL}/connect/google/redirect` | Google OAuth redirect |
| `GOOGLE_MAPS_API_KEY` | No | — | Enables `google_maps` app for all users |
| `SERPAPI_KEY` | No | — | Enables `google_flights` app via SerpAPI |
| `SLACK_CLIENT_ID` | Yes* | — | Slack OAuth client ID (*if Slack enabled) |
| `SLACK_CLIENT_SECRET` | Yes* | — | Slack OAuth client secret |
| `NOTION_CLIENT_ID` | Yes* | — | Notion OAuth client ID (*if Notion enabled) |
| `NOTION_CLIENT_SECRET` | Yes* | — | Notion OAuth client secret |
| `MONGO_URI` | Yes | — | MongoDB connection string |
| `MONGO_DB` | No | `flow_db` | MongoDB database name |
| `AGENTVERSE_API_KEY` | Yes | — | AgentVerse + ASI:ONE bearer token |
| `DOMINOS_SERVICE_URL` | No | `http://dominos:3001` | Domino's Node.js service URL |
