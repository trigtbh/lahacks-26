# barelyatwork ⚡

> **Voice-powered AI automation engine.** Speak a command, Chad builds and executes a multi-app workflow — in real time.

Built at **LA Hacks 2026** in 36 hours.

---

## What It Does

Say *"Hey Chad, when I'm running late, message my team on Slack, push my next meeting by 30 minutes, and order a Domino's pizza to the office"* — and Chad:

1. Transcribes your voice (Deepgram Nova-3)
2. Classifies intent and constructs a validated workflow (Gemma-4-26B via OpenRouter)
3. Saves it as a trigger-phrase-activated automation
4. On the next trigger — executes all steps, in order, with live context (calendar data, contacts, current time)
5. Replies in natural speech (ElevenLabs)

No app-switching. No manual configuration. Just talk.

---

## Architecture at a Glance

```
Android App  ──PCM audio──▶  FastAPI Backend  ──▶  Deepgram STT
                                   │
                    ┌──────────────┼──────────────────┐
                    ▼              ▼                   ▼
             Gemma-4-26B    Workflow Store       AgentVerse
             (Classify +    (MongoDB)           (Agent Chat)
              Validate)
                    │
                    ▼
              Executor Engine
        ┌─────────────────────────┐
        │  Gmail  │ Slack  │ Gcal │
        │ Notion  │ Drive  │ Maps │
        │ Flights │Domino's│ More │
        └─────────────────────────┘
                    │
             ElevenLabs TTS ──▶ Audio Reply
```

**Stack:** Python / FastAPI · Kotlin (Android) · React (Onboarding) · MongoDB · Docker

---

## Key Features

| Feature | Detail |
|---|---|
| **Voice-first UX** | Wake word detection, PCM streaming, TTS reply |
| **Anti-hallucination AI** | Closed-world schema + LLM validator/repair loop |
| **12+ integrations** | Gmail, Calendar, Slack, Notion, Drive, Flights, Maps, Contacts, Domino's, AgentVerse agents |
| **Dynamic params** | `calendar.next_event`, `time.now`, `user.contacts.email:Name` resolved at runtime |
| **Control flow** | `if` / `while` / `for_each` — real branching logic in voice workflows |
| **SSE streaming** | Watch each workflow step execute in real time |
| **Fuzzy triggers** | "I'm running late" fires "when i am running late" via semantic match |
| **Custom webhooks** | Zapier fallback for any app without a native handler |
| **Multi-step inference** | 2-stage LLM planner for complex cross-app tasks |

---

## Quickstart

### Prerequisites
- Docker + Docker Compose
- Python 3.11+ (for local dev)
- Android Studio (for mobile)

### 1. Configure Environment

```bash
cp backend/.env.example backend/.env
# Fill in keys (see Environment Variables below)
```

### 2. Launch Backend

```bash
cd backend
docker compose up
```

Backend runs on `http://localhost:8000` · Domino's service on `http://localhost:3001`

### 3. Onboarding Frontend (OAuth Setup)

```bash
cd onboarding
npm install && npm run dev
```

### 4. Android App

Open `mobile/` in Android Studio, set `BASE_URL` to your backend, run on device/emulator.

---

## Environment Variables

```env
# LLM
OPENROUTER_API_KEY=        # Gemma-4 via OpenRouter
LLM_MODEL=google/gemma-4-26b-a4b-it

# Speech
DEEPGRAM_API_KEY=          # STT
ELEVENLABS_API_KEY=        # TTS
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb

# Google (OAuth + APIs)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
BACKEND_URL=http://localhost:8000
GOOGLE_MAPS_API_KEY=       # optional
SERPAPI_KEY=               # optional — Google Flights

# Slack OAuth
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=

# Notion OAuth
NOTION_CLIENT_ID=
NOTION_CLIENT_SECRET=

# Database
MONGO_URI=mongodb://user:pass@host:27017/
MONGO_DB=flow_db

# Agents
AGENTVERSE_API_KEY=
```

---

## How Workflows Work

```
Voice Input
    │
    ▼
Deepgram STT → transcript
    │
    ▼
Classifier (Gemma-4) ──builds──▶ Workflow JSON
    │                              {intent, trigger_phrase, steps[]}
    ▼
Validator ──if broken──▶ Repair (LLM retry ×2)
    │
    ▼
User Confirmation ("Say yes to confirm")
    │
    ▼
Executor → each step dispatched to correct integration
    │       params resolved at runtime from context + APIs
    ▼
ElevenLabs TTS → audio reply
```

A step looks like:
```json
{
  "app": "gmail",
  "action": "send",
  "params": {
    "to": "user.contacts.email:John",
    "subject": "Running late",
    "body": "format_text:Sorry, stuck in traffic — ETA 30min"
  }
}
```

---

## Integrations

| App | Actions |
|---|---|
| **Gmail** | send, draft, search |
| **Google Calendar** | create event, update, cancel |
| **Slack** | DM, channel post, list channels |
| **Notion** | create page, append blocks, get link |
| **Google Drive** | read, create, search, share |
| **Google Flights** | search flights (via SerpAPI) |
| **Google Maps** | directions, nearby search |
| **Google Contacts** | list, search by name |
| **Domino's** | order pizza, reorder last |
| **AgentVerse** | discover and chat with any AI agent |
| **Zapier Webhooks** | custom app fallback |
| _Stubbed_ | GitHub, Spotify, Uber |

---

## API Endpoints

```
POST /audio/start          Open recording session
POST /audio/stream         Append audio chunk
POST /audio/end            Transcribe + classify + respond

POST /workflow/create      Classify → persist workflow
POST /workflow/trigger     Fire workflow by trigger phrase
POST /workflow/execute     Route text → agent or built-in
POST /workflow/execute-stream   SSE streaming execution
GET  /workflow/list/{user_id}   All saved workflows
DELETE /workflow/{id}

GET  /auth/google          Initiate Google OAuth
GET  /auth/slack           Initiate Slack OAuth
GET  /auth/notion          Initiate Notion OAuth
GET  /user/{id}/connections    Connected services

POST /user/{id}/webhooks   Register Zapier webhook
POST /user/{id}/credentials/dominos

GET  /audit/{user_id}      Execution audit trail
POST /infer/query          Multi-step task planning
```

---

## Team

Built in 36 hours at **LA Hacks 2026**.

---

## License

MIT
