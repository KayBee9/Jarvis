# Jarvis

Jarvis is a personal AI assistant app. This repository is being built in phases.

Current phase: **Phase 1 - Core Text Agent**

## Stack

- Frontend: Next.js, React, Tailwind, shadcn/ui-style local components
- Backend: FastAPI
- Database: Supabase Postgres
- AI: OpenAI Responses API
- Auth: Supabase Auth planned; Phase 1 uses a dev user locally unless JWT verification is configured

Later phases will add pgvector memory recall, Redis/Celery jobs, OpenAI Realtime voice, reminders, daily briefing, monitoring, and deployment wiring.

## Phase 1 Scope

Included:

- Browser chat UI
- FastAPI `/api/chat` endpoint
- OpenAI Responses API integration
- Conversation continuation with `previous_response_id`
- Supabase Postgres tables for conversations and messages
- Local dev fallback when `OPENAI_API_KEY` or `DATABASE_URL` is not configured
- Voice (but only with Chrome/Edge only)

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
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.2
DATABASE_URL=your_supabase_postgres_connection_string
SUPABASE_JWT_SECRET=
DEV_USER_ID=00000000-0000-0000-0000-000000000001
FRONTEND_ORIGIN=http://localhost:3000
```

`OPENAI_API_KEY` is optional for local smoke testing. Without it, the backend returns a dev-mode response.

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
5. If `OPENAI_API_KEY` is configured, Jarvis responds through the OpenAI Responses API.
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
  "response_id": "resp_..."
}
```

### `GET /api/conversations/{conversation_id}`

Returns a persisted conversation with messages. Requires `DATABASE_URL`.

## Next Phase

Phase 2 should add the memory system:

- propose memory candidates from chat
- require user approval before saving memories
- store approved memories in Supabase
- embed memories with OpenAI embeddings
- retrieve relevant memories with pgvector during chat
- add inspect/delete memory endpoints and UI

Per instruction, work stops after Phase 1 until you explicitly ask to continue.
