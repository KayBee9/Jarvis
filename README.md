# Jarvis

Jarvis is a personal AI assistant app. This repository is being built in phases.

Current phase: **Phase 1 - Core Text Agent**

## Stack

- Frontend: Next.js, React, Tailwind, shadcn/ui-style local components
- Backend: FastAPI
- Database: Supabase Postgres
- AI: Anthropic Claude API
- Auth: Supabase Auth planned; Phase 1 uses a dev user locally unless JWT verification is configured

Later phases will add pgvector memory recall, Redis/Celery jobs, higher-quality voice (e.g. Whisper + ElevenLabs), reminders, daily briefing, monitoring, and deployment wiring.

## Phase 1 Scope

Included:

- Browser chat UI
- FastAPI `/api/chat` endpoint
- Anthropic Claude API integration
- Conversation continuation by replaying full message history from Supabase on each request
- Supabase Postgres tables for conversations and messages
- Local dev fallback when `ANTHROPIC_API_KEY` or `DATABASE_URL` is not configured
- Voice input/output via Web Speech API (Chrome/Edge only)

Not included yet:


- Durable user-approved memories
- Memory search with pgvector
- Conversation summarization jobs
- Reminders
- Daily briefing
- Memory inspection/deletion UI
- Production auth flow

## Repository Layout

```text
frontend/   Next.js app
backend/    FastAPI app
```

## Backend Setup

From `backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

Edit `backend/.env`:

```env
ANTHROPIC_API_KEY=your_anthropic_api_key
ANTHROPIC_MODEL=claude-sonnet-4-6
DATABASE_URL=your_supabase_postgres_connection_string
SUPABASE_JWT_SECRET=
DEV_USER_ID=00000000-0000-0000-0000-000000000001
FRONTEND_ORIGIN=http://localhost:3000
```

`ANTHROPIC_API_KEY` is optional for local smoke testing. Without it, the backend returns a dev-mode response.

`DATABASE_URL` is optional for local smoke testing. Without it, chat still works, but conversation messages are not persisted.

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

## Supabase Setup

Create a Supabase project and run this migration in the SQL editor:

```text
backend/supabase/migrations/001_phase_1_core_chat.sql
```

For Phase 1, the FastAPI backend filters all conversation and message reads/writes by `user_id`. Full Supabase Auth integration comes later; if `SUPABASE_JWT_SECRET` is empty, the API uses `DEV_USER_ID`.

## Frontend Setup

From `frontend/`:

```bash
npm install
copy .env.example .env.local
npm run dev
```

Edit `frontend/.env.local` if your backend is not running on port `8000`:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Open:

```text
http://localhost:3000
```

## Operating Phase 1

1. Start the FastAPI backend from `backend/`.
2. Start the Next.js frontend from `frontend/`.
3. Open `http://localhost:3000`.
4. Send a message in the chat box.
5. If `ANTHROPIC_API_KEY` is configured, Jarvis responds through the Anthropic Claude API.
6. If `DATABASE_URL` is configured and the Supabase migration has been run, messages are persisted to Supabase.

## API

### `POST /api/chat`

Request:

```json
{
  "message": "Hello Jarvis",
  "conversation_id": null
}
```

Response:

```json
{
  "conversation_id": "uuid",
  "assistant_message": "Hi there...",
  "response_id": "msg_..."
}
```

### `GET /api/conversations/{conversation_id}`

Returns a persisted conversation with messages. Requires `DATABASE_URL`.

## Known Gaps / Future Work

- **Conversation history cache** — the backend currently fetches the full conversation history from Supabase on every chat request to build the message context for Claude. A future improvement is to keep each session's history in memory (e.g. Redis or an in-process cache keyed by `conversation_id`) so the DB is only hit on the first request of a session, not every turn.
- **Voyage AI embedding provider** — embeddings currently run locally via `sentence-transformers` (`all-MiniLM-L6-v2`). The `EmbeddingProvider` abstraction in `app/embeddings.py` is designed to be swappable; adding a `VoyageProvider` behind the same interface would let `EMBEDDING_PROVIDER=voyage` in `.env` switch to Voyage's hosted API for better embedding quality (at the cost of an API key and per-request network latency).
- **Auto-extraction of memories with approval** — memory saving is currently fully manual: the user clicks "Save to memory" on a message and edits the text before storing. A future improvement is to run a second Claude call after each chat turn asking what durable facts the user shared, then surface those candidates in the UI with Save/Skip buttons. Approved candidates flow through the existing embed-and-store pipeline. Done well, this makes Jarvis feel proactive rather than a passive notepad — but requires careful prompt engineering to avoid junk suggestions.
- **Clean newlines from memories before saving** — chat messages can contain intentional newlines (Shift+Enter for multi-line input). When such a message is saved as a memory, the newlines are stored verbatim. For a well-formed knowledge base, the save flow should strip or collapse newlines before persisting (either automatically, or by having the edit-before-save modal default to a flattened version of the source text).
- **Voice-reactive Jarvis orb** — the background orb currently pulses on a fixed timer. When Jarvis speaks (TTS), the orb's pulse should sync to the rhythm/amplitude of the voice output, similar to the Iron Man arc reactor reacting to JARVIS's speech. Likely implementation: tap the Web Audio API's `AnalyserNode` on the TTS audio stream, sample the frequency/amplitude in real time, and drive the orb's `transform: scale()` and `opacity` from those values via CSS custom properties.
- **Loading state during chat responses** — Claude can take 1-3 seconds to reply. The frontend currently has no visual feedback during that wait: the input stays editable, the button looks the same, and the user sees nothing happen until the response arrives. A future improvement is to disable the input while a request is in flight and show a "Jarvis is thinking..." indicator in the messages area (or pulse the orb faster as a signal).
- **Batched-thought input (stack of inputs)** — instead of the standard one-message-at-a-time chat, let the user queue up multiple thoughts before sending. UX: each thought is added to a visible stack above the input via a `+` button; the Send button submits the whole stack as one message to Claude formatted as a bulleted list, displayed in the chat as a single combined user bubble. Useful when the user wants to dump several related questions or points and get one cohesive reply addressing all of them. Each stack item needs a stable id and a remove (×) button.
- **Local voice (STT + TTS)** — voice is not yet wired into the new frontend. The intended stack is fully local and free: `faster-whisper` for speech-to-text and `Piper` or `Kokoro` for text-to-speech. Architecture mirrors the embedding provider — load the model at backend startup via lifespan, expose `POST /api/transcribe` and `POST /api/speak` endpoints, and have the frontend record audio via `MediaRecorder` for input and play back the audio response for output. Reference repos:
  - faster-whisper (STT): https://github.com/SYSTRAN/faster-whisper
  - Piper (TTS, maintenance-mode original): https://github.com/rhasspy/piper
  - Piper (TTS, active fork): https://github.com/OHF-Voice/piper1-gpl
  - Piper voice samples: https://rhasspy.github.io/piper-samples/
  - Kokoro (TTS, 82M params, high quality): https://github.com/hexgrad/kokoro

## Next Phase

Phase 2 should add the memory system:

- propose memory candidates from chat
- require user approval before saving memories
- store approved memories in Supabase
- embed memories with a local model (e.g. `sentence-transformers`) by default, with Voyage AI as a configurable alternative provider behind a shared abstraction
- retrieve relevant memories with pgvector during chat
- add inspect/delete memory endpoints and UI

Per instruction, work stops after Phase 1 until you explicitly ask to continue.
