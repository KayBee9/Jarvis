# Jarvis

> A local-first, voice-driven personal AI assistant that remembers you across devices.

I built Jarvis because commercial assistants have three shortcomings I couldn't work around: they don't remember what you told them last week, they live in someone else's cloud, and they can't be reshaped to match your voice or judgment. Jarvis is my attempt to fix all three. It runs from a single machine on my Tailscale tailnet, is reachable from any device I own, and keeps a persistent semantic memory of facts I've shared.

The project has become a testbed for a set of engineering problems I find interesting: cross-device state consistency without a coordination server, streaming LLM responses with mid-flight cancellation, and turning conversational chat into a durable knowledge base that the assistant can reason over.

## Highlights

- **Cross-device continuity** — start a conversation on desktop, keep it going on phone. Both devices see live updates via Server-Sent Events, and a five-minute idle rule closes and summarizes a session automatically.
- **Streaming replies with mid-flight interrupts** — send follow-up messages while Jarvis is still generating; the next reply naturally addresses everything he hasn't answered yet. No queue-and-wait UX, no lost context.
- **LLM-driven memory reconciliation** — the assistant classifies each new fact against similar existing memories as `ADD`, `REPLACE`, `DELETE`, or `SKIP`, and destructive actions surface as pending changes for user approval.
- **Batched fact extraction** — memory extraction runs on windows of conversation rather than per-message, giving the extractor context to distinguish durable traits from transient intent, and running many fewer LLM calls than a naive approach.
- **Voice pipeline with barge-in** — tap the mic while Jarvis is speaking and audio stops immediately. Browser-side VAD auto-ends the recording when you finish talking. iOS Safari autoplay is worked around with a silent-WAV unlock on first tap.
- **Runs entirely on your machine** — local LLM via Ollama, local embeddings via `sentence-transformers`, local Piper TTS, local Whisper STT. The only remote component today is the Postgres backing store, and swapping to local Postgres is a config change.

## Architecture

```
                     ┌──────────────────────┐
                     │  Browser (any device)│
                     │  Next.js + Tailwind  │
                     └──────────┬───────────┘
                                │ HTTPS (Tailscale cert)
                                ▼
   ┌────────────────────────────────────────────────────────┐
   │                     FastAPI backend                    │
   │                                                        │
   │  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
   │  │ /api/chat  │  │ /api/speak │  │  /api/memories/* │  │
   │  │(streaming) │  │  (Piper)   │  │                  │  │
   │  └─────┬──────┘  └────────────┘  └────────┬─────────┘  │
   │        │                                  │            │
   │        │       ┌────────────────┐         │            │
   │        └──────▶│  Agent layer   │◀────────┘            │
   │                │  (Ollama /     │                      │
   │                │   Anthropic)   │                      │
   │                └────────┬───────┘                      │
   │                         │                              │
   │  ┌──────────────────────┴─────────────────────────┐    │
   │  │           Async background workers             │    │
   │  │  consolidation (debounced) • finalize_after    │    │
   │  │  reconciliation lock • startup recovery        │    │
   │  └──────────────────────┬─────────────────────────┘    │
   └─────────────────────────┼──────────────────────────────┘
                             ▼
                  ┌─────────────────────┐
                  │  Postgres + pgvector│
                  │  conversations,     │
                  │  messages, memories,│
                  │  pending_changes    │
                  └─────────────────────┘
```

| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js 16 (React 19), Tailwind v4 | Dark, minimal, browser-only |
| Backend | FastAPI, `asyncpg` | Single-process async |
| Database | Postgres + `pgvector` (Supabase today, local Postgres capable) | Vector search on 384-dim embeddings |
| LLM | Ollama (`llama3.2:3b` default), Anthropic Claude fallback | Swappable behind an `LLMProvider` protocol in `agent.py` |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Local, 384-dim, offline |
| STT | `faster-whisper` (base) | CPU-only |
| TTS | Piper (`en_US-amy-medium`) | CPU-only |
| Voice activity | Browser-side (`AudioContext` + `AnalyserNode`) | Pure JS, offline |
| Multi-device transport | Server-Sent Events | Per-conversation subscriber count for presence |
| HTTPS access | Tailscale MagicDNS + `tailscale cert` | Same cert for FE and BE |

## Notable Engineering

### Cross-device state sync

The core question: two devices are open at the same time, both viewing the same conversation. How do they stay in sync without a coordination server?

Each conversation has a Server-Sent Events endpoint at `GET /api/conversations/{id}/stream`. When a browser opens the conversation, it subscribes to that stream. New messages posted from any device fan out to every subscribed listener. Presence is tracked with a module-level `defaultdict[UUID, int]` counting active subscribers per conversation, incremented on connect and decremented in the endpoint's `finally` block when the SSE loop's write fails.

The interesting problem was **distinguishing "user closed the app" from "user just refreshed the tab."** Refresh causes a brief SSE disconnect that shouldn't tear the session down. The solution is a two-part rule:
- `sessionStorage` persists the `conversationId` across refreshes, so the frontend restores the same conversation immediately.
- A five-minute grace window on the backend: a conversation stays "active" as long as at least one device has been subscribed within the last five minutes, tracked via a debounced `finalize_after` background task. On real closure, that task runs consolidation over any residual messages and generates a conversation summary.
- Cross-server-restart recovery: on startup, `recover_pending_finalizations` scans for any conversation whose `summary is null` and schedules `finalize_after` with a delay computed from the elapsed idle time, so five-minute finalization survives backend restarts.

### Streaming chat with mid-flight interrupts

The chat endpoint is a `StreamingResponse` that yields tokens from Ollama as they generate. The frontend reads the response body via `ReadableStream.getReader()` and appends each chunk into a live "Jarvis" bubble as tokens arrive.

The subtler problem: **what happens when the user sends a new message while Jarvis is still generating a reply?** Two invariants had to hold together:

1. The interrupted user message must stay in DB as unanswered, so Jarvis's next reply addresses it.
2. No partial "phantom" reply should land in DB — otherwise refresh would show a reply the user never saw.

The solution:
- The frontend tracks `isGenerating` state and holds an `AbortController` for the in-flight fetch. On new Send, if `isGenerating` is true, the fetch is aborted (audio is also stopped, always).
- The backend's streaming generator wraps the token loop in `try/except/else`. `CancelledError` (thrown when the client disconnects) is re-raised without saving. Only the `else` branch — reached on normal completion — writes the assistant message and fires the consolidation trigger.
- A helper, `merge_consecutive_user_turns`, collapses multiple unanswered user rows in history into a single composite user message before sending to the LLM. Small models like `llama3.2:3b` handle one composite turn much better than a `[user, user, user]` sequence.
- The conversation ID is generated client-side into a `useRef` so rapid back-to-back sends all reference the same UUID (React state updates async; the ref updates synchronously). The backend upserts the row if the ID is new.

The result: you can talk over Jarvis. He'll finish addressing you when he catches up.

### Memory pipeline

Every fact Jarvis learns flows through the same `save_or_reconcile` function. Before writing anything, it:

1. Embeds the new fact and runs a similarity search against existing memories with a `min_similarity=0.82` threshold.
2. Passes the new fact and up-to-five similar existing memories to an LLM reconciler that returns one of four decisions: `ADD` (fact is independent), `REPLACE` (updates an existing fact — e.g. moved cities), `DELETE` (negates an existing fact — "I'm not vegetarian anymore"), or `SKIP` (literally the same fact restated).
3. Executes on the decision. `ADD` and `SKIP` are automatic. `REPLACE` and `DELETE` are stored as `pending_memory_changes` that surface in the UI for user approval.

A global `asyncio.Lock` around this function prevents duplicate saves when concurrent extractions produce overlapping facts. Batched consolidation debounces triggers, so a rapid burst of messages fires one extraction pass rather than one per message.

The reconciler's prompt was iterated based on real usage — early versions collapsed sibling facts like "likes chocolate" and "likes meat" into one, because they're topically close. The current prompt uses worked examples for `ADD` vs `SKIP` boundaries and explicit anti-examples for meta-statements the extractor kept surfacing ("Oscar wants to discuss X").

### Voice pipeline

Voice is fully local: Whisper for STT, Piper for TTS, and browser-side VAD via `AudioContext.AnalyserNode`. Three pieces made the mobile UX work:

- **iOS Safari autoplay unlock.** iOS blocks `audio.play()` until a user gesture. A persistent `<audio>` element gets its first play call with a tiny silent WAV data URI during the first `mousedown`/`touchstart`, after which it's trusted for all subsequent Piper output in the session.
- **Voice barge-in.** Tapping the mic pauses Jarvis's TTS immediately. If the recording turns into a Send, the streaming chat endpoint's abort logic takes over.
- **Tunable VAD.** Silence threshold and duration are exposed as constants in `startRecording`, tuned for a quiet room but easy to bump for noisier environments.

The `TTSProvider` abstraction is in place for a future voice-cloning swap — see Explored Paths for what that experiment revealed.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/chat` | POST | Send a message. Streams the reply as raw text; the conversation ID is returned in the `X-Conversation-Id` response header. |
| `/api/conversations/{id}` | GET | Fetch a persisted conversation with all its messages. |
| `/api/conversations/{id}/stream` | GET | Server-Sent Events subscription for cross-device sync. |
| `/api/conversations/active` | GET | Return the current "active" conversation across all devices, or `null`. |
| `/api/greeting` | GET | Return the startup greeting Jarvis generated during LLM warmup. |
| `/api/memories` | GET/POST | List or add a memory. `POST` runs the new fact through the reconciliation pipeline. |
| `/api/memories/{id}` | DELETE | Remove a memory. |
| `/api/memory-changes` | GET | List pending `REPLACE`/`DELETE` changes awaiting approval. |
| `/api/memory-changes/{id}/approve` | POST | Approve a pending change and apply it. |
| `/api/memory-changes/{id}/skip` | POST | Discard a pending change. |
| `/api/speak` | POST | Text → WAV bytes via Piper. |
| `/api/transcribe` | POST | Multipart audio upload → text via faster-whisper. |
| `/health` | GET | Backend + database health check. |

## Running It Yourself

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` with your `DATABASE_URL` (Supabase or local Postgres) and `FRONTEND_ORIGIN`. Then download the Piper voice files into `backend/models/piper/`:
- [en_US-amy-medium.onnx](https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx)
- [en_US-amy-medium.onnx.json](https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json)

Run migrations and start:

```bash
python migrate.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `curl http://localhost:8000/health`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`.

### Ollama (local LLM)

Install [Ollama](https://ollama.com) and pull the default model:

```bash
ollama pull llama3.2:3b
```

The backend will call it on `http://localhost:11434`.

### Multi-device via Tailscale (optional)

Jarvis runs over HTTPS via a Tailscale MagicDNS hostname so it's reachable from phone or LAN — iOS Safari requires a secure context for mic access. The setup involves generating certs with `tailscale cert`, wiring them into both the frontend `next dev --experimental-https` flags and uvicorn's `--ssl-*` flags, and updating `FRONTEND_ORIGIN` and `NEXT_PUBLIC_API_BASE_URL` to the MagicDNS hostname. This is documented in more detail in the project's setup notes.

## Voice Tuning

Three knobs in `frontend/app/page.tsx` inside `startRecording`:

| Parameter | Default | What it does |
|---|---|---|
| `silenceThreshold` | `8` | RMS amplitude below this is treated as "silence" (0-127 range). |
| `silenceDuration` | `1200` ms | How long silence must persist before the recorder auto-stops. |
| `setInterval(..., 50)` | `50` ms | VAD polling rate (20 Hz). |

## Roadmap

- **LoRA fine-tuning** on samples of my own writing, converted to GGUF and loaded via Ollama's `Modelfile`.
- **Built-in calendar and reminders** — own tables and CRUD, so Jarvis can create/query/update events conversationally without an external API.
- **Local Postgres + pgvector** for full-offline operation. The `DATABASE_URL` abstraction makes this a config-level swap.
- **Smarter memory retrieval** as the memory set grows — semantic top-k, always-included core facts, or LLM-decided retrieval via tool calls.
- **Voice-reactive Jarvis orb** — sync the background pulse to the TTS output stream via `AnalyserNode`.
- **Tauri desktop app** bundling LLM, voice models, and Postgres for one-click install.
- **Dedicated device** — Raspberry Pi 5 or NUC running everything 24/7.

## Explored Paths

**Voice cloning (XTTS-v2 or F5-TTS)** — attempted on the `voice-cloning-xtts` branch, abandoned mid-experiment due to a dependency chain that doesn't compose cleanly on Python 3.13 + PyTorch 2.12 + Windows: `torchaudio` missing → `transformers.pytorch_utils.isin_mps_friendly` removed → `torchcodec` missing → FFmpeg missing → PyTorch/torchcodec version incompatibility. The `TTSProvider` abstraction in `app/voice.py` is shaped to accept an `XTTSProvider` implementation; the branch documents the code shape. Revisit paths when picking this up again: rebuild the venv with Python 3.11 and pinned older PyTorch (~2.4) to match torchcodec's compatibility matrix, try [F5-TTS](https://github.com/SWivid/F5-TTS) which has a lighter dependency footprint, or wait for the `coqui-tts` Idiap fork to publish releases against newer torch.