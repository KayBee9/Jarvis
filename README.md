# Jarvis

A personal AI assistant — built for one user (me). The goal is a private, locally-runnable assistant that can chat, remember facts I share, talk back, and eventually learn to behave like me.

## Direction

- **Single-user, no auth.** Multi-user scaffolding (JWT verification, `user_id` filtering, row-level security) is being removed.
- **Local-first AI.** Currently uses Anthropic Claude; transitioning to a local LLM via Ollama (Llama 3.1 8B as the starting point) so chat works offline and stays private.
- **Multi-device access.** Will eventually be reachable from laptop, phone, desktop, and ultimately a dedicated device.
- **Personalization.** A strong persona prompt + the existing semantic memory layer first. LoRA fine-tuning on samples of my own writing later.

The previous version (multi-user-capable, Claude-only) is preserved on the `multi-user-snapshot` branch.

## Session Handoff

**For any AI assistant (or future me) continuing this project — read this first to pick up where we left off.** Keep this section updated at the end of each session.

- **Current step in the Roadmap:** Step 5 (LoRA fine-tuning) is next. Steps 1-4 complete.
- **Working style:** Step-by-step teaching. Explain each change; don't dump full solutions in one go. Wait for confirmation before moving to the next sub-step. Ask before big design commits.
- **Recently added (last session):**
  - Step 4 done: LAN + remote access via Tailscale with real Let's Encrypt HTTPS certs. Backend + frontend both serve HTTPS from the same cert (`backend/certs/desktop-k5pi7kg.tail5ce535.ts.net.{crt,key}`, gitignored).
  - `backend/start.ps1` script bakes the SSL flags into the uvicorn command; frontend's `package.json` dev script bakes the `--experimental-https` flags.
  - iOS Safari audio autoplay unlock: silent-WAV played on first touch/mousedown, persistent `audioRef` reused for all subsequent TTS playback.
  - `crypto.randomUUID()` replaced with a `generateId()` polyfill using `crypto.getRandomValues()` since `randomUUID` requires a secure context we don't always have (LAN HTTP was a stepping stone).
  - Mobile polish: `viewport` export with `viewportFit: "cover"`, `h-[100dvh]` on html/body, `text-base` on the chat textarea (prevents iOS auto-zoom), safe-area padding at the bottom of the chat column.
- **Design choices worth respecting (don't undo without discussing):**
  - Memory injection = "inject-all" while the memory set is small. See "Smarter memory retrieval" for the scaling escape hatch.
  - No approval step for ADD / SKIP actions — only REPLACE / DELETE need approval.
  - Both auto-extract and manual-save go through the shared `save_or_reconcile` helper in `main.py`.
  - Regex-based JSON parsing for `extract_memories` / `reconcile_memory` — fragile but works. Upgrade to Ollama's `format="json"` if it starts failing more often.
  - Certs live in `backend/certs/` and are shared with the frontend via relative path (`../backend/certs/...` in `package.json`). Both servers serve HTTPS with the same Tailscale-provisioned cert.
  - All URLs use the MagicDNS hostname (`desktop-k5pi7kg.tail5ce535.ts.net`) not IPs — the cert is only valid for the hostname.
- **Known open bugs (documented in "Known Gaps"):**
  - Reconciler drops sibling facts as duplicates (e.g. "I like chocolate and meat" saves only one). Quickest fix to try: raise `min_similarity` in `save_or_reconcile` (main.py) from 0.5 to 0.75.
- **Immediate next action:** Start step 5 (LoRA fine-tuning). Sub-tasks that need scoping: (1) collect a personal dataset — sources could be exported chats, journal entries, emails, this Jarvis conversation history itself. (2) Format for training (Alpaca-style, ShareGPT, or chat template — depends on tooling). (3) Pick training tool (Unsloth is fastest on modest hardware; Axolotl is more flexible; MLX-LM if on Mac). (4) Rent a GPU or run locally if the user has one. (5) Convert LoRA to GGUF and load into Ollama with `Modelfile`.
- **Blockers / open questions for step 5:** Does the user have GPU access, or need to rent? What sources of "your writing" are willing/available to use as training data? What size base model to fine-tune (`llama3.1:8b` matches current runtime)?

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
.\start.ps1
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

## Tailscale / Multi-Machine Setup

Jarvis runs over HTTPS via a Tailscale MagicDNS hostname (not plain `localhost`) so it works from phone/LAN too — iOS Safari requires a secure context for mic access and `crypto.randomUUID()`. That hostname is hardcoded in **four places**. Moving to a different machine (which gets its own Tailscale hostname) means updating all four:

| File | What to change |
|---|---|
| `frontend/.env.local` | `NEXT_PUBLIC_API_BASE_URL=https://<hostname>:8000` |
| `frontend/package.json` | `dev` script's `--experimental-https-key` / `--experimental-https-cert` paths |
| `frontend/next.config.ts` | `allowedDevOrigins` |
| `backend/start.ps1` | `--ssl-keyfile` / `--ssl-certfile` paths |
| `backend/.env` | `FRONTEND_ORIGIN` — must match the frontend's actual origin or CORS blocks every request |

Certs live in `backend/certs/<hostname>.{crt,key}` (gitignored) and must be (re)generated per machine:

```powershell
mkdir certs
tailscale cert --cert-file certs/<hostname>.crt --key-file certs/<hostname>.key <hostname>
```

**Constraints:**
- Tailscale hostnames are unique per tailnet — you can't rename one device to match another while both are online. Only rename if you're retiring the old one.
- A fresh Tailscale install (e.g. after reinstalling Windows) can mint a *different* hostname even on what feels like "the same machine." Check `tailscale status` or the admin console (login.tailscale.com/admin/machines) rather than assuming it matches a prior session.

**Running fully locally, no Tailscale/certs at all:** use plain `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` (drop the `--ssl-*` flags) and `next dev` (drop `--experimental-https*` in `package.json`), with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` and `FRONTEND_ORIGIN=http://localhost:3000`.

**First-time machine setup gotchas:**
- PowerShell blocks `.ps1` scripts by default → `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, or run once via `powershell -ExecutionPolicy Bypass -File .\start.ps1`.
- Node.js/npm and Ollama are separate installs, not pulled in by `pip install` or `npm install` — install both directly, and open a **new** terminal afterward so PATH updates take effect.
- Ollama does not auto-pull a model on first API request — `ollama pull <model>` explicitly before starting the backend.
- `backend/.venv`, `backend/.env`, and `backend/certs/` are all gitignored and machine-specific — recreate them fresh on every new machine (see Backend Setup above).

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
- **Reconciler drops sibling facts as duplicates** — observed: a message like "I like chocolate and meat" ends up with only ONE fact saved (either "Oscar likes chocolate" OR "Oscar likes meat"), never both. Likely cause: after the extractor produces both facts, the first is saved as ADD; when the second fact runs through `save_or_reconcile`, `search_memories` finds the first as semantically similar (both are food preferences), and the LLM reconciler classifies it as SKIP or REPLACE thinking they're the same fact. Reconciler is too aggressive on topical similarity vs. actual conflict. Fix candidates: (1) tighten the `RECONCILE_PROMPT` — spell out that SKIP means "literally the same fact restated," and topical overlap doesn't count. Include a few-shot example like `"Oscar likes chocolate" + "Oscar likes meat"` → `ADD` (different preferences). (2) Raise `min_similarity` on the pre-reconciliation search from 0.5 to 0.7-0.8, so only genuinely near-identical facts trigger reconciliation at all. (3) As a diagnostic, log the reconciler's decision + reasoning to console so we can see which of the two mechanisms is failing.
- **Smarter memory retrieval** — the chat endpoint currently injects ALL stored memories into every system prompt. This is fine while the memory set is small (~50-200 facts), but eats context window once it grows past several hundred. Strategies for later, roughly ordered by complexity:
  1. **Lower the threshold + larger top-k** — switch back to `search_memories` but with `min_similarity = 0` and `top_k = 20`. Cheapest first attempt. Still misses meta-queries.
  2. **Meta-query detection** — classify questions like "what do you know about me", "tell me about myself", "summarize what you remember" with keyword patterns or a small classifier; for those, fall back to "inject all". Otherwise use semantic search.
  3. **Always-included core set** — add an `is_core` boolean column to `memories`. Manually mark important facts (name, allergies, key preferences) as core; always inject those plus top-k semantic search for the rest.
  4. **Recency hybrid** — always include the N newest memories plus top-k semantic matches. Cheap, biases toward current life context.
  5. **LLM-decided retrieval** — give Jarvis a `get_all_memories(filter?)` tool it can call when it judges the query needs it. Most flexible, most complex; requires function-calling-capable model.
- **Voice-reactive Jarvis orb** — the background orb currently pulses on a fixed timer. When Jarvis speaks, the orb's pulse should sync to the rhythm/amplitude of the voice output. Likely implementation: tap the Web Audio API's `AnalyserNode` on the TTS audio stream, sample frequency/amplitude in real time, and drive the orb's `transform: scale()` and `opacity` via CSS custom properties.
- **Concurrent message handling** — if I send a second message before the first reply arrives, both requests run in parallel with no coordination. Observed issues so far: memory auto-extraction runs on both messages independently, so the same fact can get saved twice; chat history for the second message doesn't include the first (still in-flight) turn; pending-change reconciliation might race and both classify against the same stale memory set. Options for later, roughly ordered by simplicity: (1) **frontend queuing** — disable the input while a request is in flight and queue any Enter/Send presses to run sequentially. Simplest and covers the common case. (2) **Per-conversation lock on the backend** — use an in-process `asyncio.Lock` keyed by `conversation_id` to serialize requests for the same conversation. Protects against multi-device concurrency too. (3) **Idempotency keys** — client generates a UUID per request, backend deduplicates. Correct but heavy.
- **Batched-thought input (stack of inputs)** — let me queue up multiple thoughts before sending. Each thought is added to a visible stack above the input via a `+` button; the Send button submits the whole stack as one bulleted message to the LLM, displayed in the chat as a single combined user bubble.
- **Local Postgres + pgvector** — for full offline operation, replace Supabase with a local Postgres instance (or SQLite + `sqlite-vec` for simpler distribution). The `DATABASE_URL` abstraction makes this a config-level change.
- **Built-in calendar and reminders** — rather than integrating with phone-native Calendar/Reminders (Google Calendar API, iCloud CalDAV, etc.), build this functionality directly into Jarvis: own tables (events, reminders with due dates/recurrence), own CRUD endpoints, and Jarvis able to create/query/update them conversationally. Keeps everything local-first and inside Jarvis's own data model instead of depending on a third-party account/API. Tradeoff (discussed and accepted): loses native OS integration (widgets, notifications, cross-device sync) that Google/Apple's apps already provide for free — deliberately choosing full control over that convenience.
- **Voice cloning (XTTS-v2 or F5-TTS)** — attempted on the `voice-cloning-xtts` branch, abandoned mid-experiment due to a dependency chain that doesn't work cleanly on our stack (Python 3.13 + PyTorch 2.12 + Windows). Chain of issues encountered, in order: `torchaudio` missing → `transformers.pytorch_utils.isin_mps_friendly` removed → `torchcodec` missing → FFmpeg missing → PyTorch/torchcodec version incompatibility. The `TTSProvider` abstraction in `app/voice.py` is ready to accept an `XTTSProvider` — the code shape is documented on the branch. Revisit options when picking this up again: (1) rebuild the venv with Python 3.11 and pinned older PyTorch (2.4-ish) to match torchcodec's compatibility matrix, (2) try [F5-TTS](https://github.com/SWivid/F5-TTS) instead — lighter dependency footprint, MIT license, similar zero-shot cloning, (3) wait for the `coqui-tts` Idiap fork to publish releases against newer torch.


- **Persona prompt iteration** — the `SYSTEM_PROMPT` in `agent.py` is v1 and needs a tuning pass based on real-usage annoyances (bad openers, unwanted disclaimers, tone).