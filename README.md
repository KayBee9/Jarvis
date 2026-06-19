# Jarvis

A personal AI assistant — built for one user (me). The goal is a private, locally-runnable assistant that can chat, remember facts I share, talk back, and eventually learn to behave like me.

## Direction

- **Single-user, no auth.** Multi-user scaffolding (JWT verification, `user_id` filtering, row-level security) is being removed.
- **Local-first AI.** Currently uses Anthropic Claude; transitioning to a local LLM via Ollama (Llama 3.1 8B as the starting point) so chat works offline and stays private.
- **Multi-device access.** Will eventually be reachable from laptop, phone, desktop, and ultimately a dedicated device.
- **Personalization.** A strong persona prompt + the existing semantic memory layer first. LoRA fine-tuning on samples of my own writing later.

The previous version (multi-user-capable, Claude-only) is preserved on the `multi-user-snapshot` branch.

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js, React, Tailwind | Dark, minimal, browser-only |
| Backend | FastAPI | Async, single-process |
| Database | Supabase Postgres + pgvector | Local Postgres possible later |
| LLM | Anthropic Claude (today) → Ollama local LLM (next) | Swappable via a provider abstraction in `agent.py` |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Local, 384-dim, free |
| STT | `faster-whisper` (base model) | Local, runs on CPU |
| TTS | Piper (`en_US-amy-medium`) | Local, runs on CPU |
| Voice activity | Browser-side VAD via `AudioContext` | Pure JS, offline |

## Repository Layout

```text
frontend/                  Next.js app
backend/                   FastAPI app
backend/models/piper/      Piper voice model files (gitignored)
backend/supabase/migrations/   SQL migrations applied via migrate.py
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
FRONTEND_ORIGIN=http://localhost:3000
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=all-MiniLM-L6-v2
PIPER_MODEL_PATH=models/piper/en_US-amy-medium.onnx
WHISPER_MODEL=base
```

Download the Piper voice files into `backend/models/piper/`:
- [en_US-amy-medium.onnx](https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx)
- [en_US-amy-medium.onnx.json](https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json)

Run migrations and start the backend:

```bash
python migrate.py
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

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

Open `http://localhost:3000`.

## API

### `POST /api/chat`
Send a message, get a reply. Maintains conversation context via `conversation_id`.

```json
{ "message": "Hello", "conversation_id": null }
```

### `GET /api/conversations/{id}`
Fetch a persisted conversation with all its messages.

### `POST /api/memories`
Save a fact: `{ "content": "I prefer tea over coffee" }`. Stores text + embedding for semantic retrieval.

### `GET /api/memories`
List all saved memories.

### `DELETE /api/memories/{id}`
Remove a saved memory.

### `POST /api/transcribe`
Multipart audio upload → text. Uses faster-whisper.

### `POST /api/speak`
JSON `{ "text": "..." }` → WAV audio bytes. Uses Piper.

## Voice Tuning

The frontend mic uses browser-side Voice Activity Detection (VAD) to auto-stop recording after silence and auto-send the transcript to Jarvis. Three knobs live in `frontend/app/page.tsx` inside `startRecording`:

| Parameter | Default | What it does | When to change |
|---|---|---|---|
| `silenceThreshold` | `8` | RMS amplitude below this is treated as "silence" (range ~0-127) | Increase to 12-15 if you're in a noisy room and recording never auto-stops. Decrease if it cuts you off mid-word. |
| `silenceDuration` | `1200` ms | How long silence must persist before the recorder stops | Lower (e.g. 800ms) for snappier responses. Higher (e.g. 2000ms) if you tend to pause mid-thought. |
| `setInterval(..., 50)` | `50` ms | Polling rate for the VAD loop (20Hz) | Almost never needs changing. Higher = lower CPU; lower = faster reaction. |

The VAD is fully client-side — pure browser APIs (`AudioContext`, `AnalyserNode`), no network or backend involvement, so it works offline.

## Roadmap

Steps in roughly the order they'll be done:

1. **Strip auth and `user_id` everywhere.** Remove `auth.py` JWT, drop `user_id` columns via migration, remove RLS policies. Backend becomes single-user.
2. **Swap Claude for Ollama.** Add `OllamaProvider` next to the existing Anthropic call in `agent.py`. Default model: `llama3.1:8b`.
3. **Write a strong persona system prompt.** Capture voice, values, defaults. Iterate as I use it.
4. **Bind the backend to `0.0.0.0`** and connect from my phone over LAN. Optionally Tailscale for remote.
5. **LoRA fine-tuning.** Collect a personal dataset (messages, journal, emails). Train a persona adapter.
6. **Package as a desktop app** via Tauri. Bundle the LLM, voice models, and Postgres for one-click install.
7. **Dedicated device.** Raspberry Pi 5 or small NUC running everything 24/7.

## Known Gaps / Future Work

- **Conversation history cache** — the backend currently fetches the full conversation history from Supabase on every chat request. A future improvement is to keep each session's history in memory (e.g. Redis or an in-process cache keyed by `conversation_id`) so the DB is only hit on the first request of a session, not every turn.
- **Voyage AI embedding provider** — embeddings currently run locally via `sentence-transformers`. The `EmbeddingProvider` abstraction in `app/embeddings.py` is designed to be swappable; adding a `VoyageProvider` behind the same interface would let `EMBEDDING_PROVIDER=voyage` in `.env` switch to Voyage's hosted API for better embedding quality.
- **Auto-extraction of memories with approval** — memory saving is currently fully manual: I click "Save to memory" on a message and edit before storing. A future improvement is to run a second LLM call after each chat turn asking what durable facts I shared, then surface those candidates in the UI with Save/Skip buttons.
- **Clean newlines from memories before saving** — chat messages can contain intentional newlines (Shift+Enter for multi-line input). When such a message is saved as a memory, the newlines are stored verbatim. For a well-formed knowledge base, the save flow should strip or collapse newlines before persisting.
- **Voice-reactive Jarvis orb** — the background orb currently pulses on a fixed timer. When Jarvis speaks, the orb's pulse should sync to the rhythm/amplitude of the voice output. Likely implementation: tap the Web Audio API's `AnalyserNode` on the TTS audio stream, sample frequency/amplitude in real time, and drive the orb's `transform: scale()` and `opacity` via CSS custom properties.
- **Loading state during chat responses** — local LLMs can take longer than Claude to reply. The frontend currently has no visual feedback during that wait. Disable the input while a request is in flight and show a "thinking" indicator (or pulse the orb faster).
- **Batched-thought input (stack of inputs)** — let me queue up multiple thoughts before sending. Each thought is added to a visible stack above the input via a `+` button; the Send button submits the whole stack as one bulleted message to the LLM, displayed in the chat as a single combined user bubble.
- **Conversation history restore on refresh** — currently a page refresh loses all messages in the visible chat. Restore from Supabase using a `conversation_id` saved in `sessionStorage`.
- **Local Postgres + pgvector** — for full offline operation, replace Supabase with a local Postgres instance (or SQLite + `sqlite-vec` for simpler distribution). The `DATABASE_URL` abstraction makes this a config-level change.