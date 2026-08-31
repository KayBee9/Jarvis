from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID, uuid4

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

import asyncpg
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app import agent, embeddings, memories, voice
from app.config import get_settings
from app.db import (
    add_message,
    create_conversation,
    database,
    fetch_conversation,
    get_db,
    fetch_messages,
    get_unconsolidated_count,
    fetch_unconsolidated_messages,
    update_last_consolidated,
    fetch_conversation_summary,
)
from app.models import (
    ChatRequest,
    ChatResponse,
    Conversation,
    Memory,
    MemoryCreateRequest,
    SpeakRequest,
    PendingMemoryChanges,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await database.connect()
    embeddings.init_provider()
    agent.init_provider()
    voice.init_tts()
    voice.init_stt()
    global startup_greeting
    startup_greeting = await agent.warm_up_and_greet()
    if startup_greeting:
        print(f"[warmup] greeting ready: {startup_greeting}")
    asyncio.create_task(recover_pending_finalizations())
    yield
    await database.close()


settings = get_settings()
app = FastAPI(title="Jarvis API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Conversation-Id"],
)

# Counts active SSE subscribers per conversation. When 0, the entry is removed.
active_streams: defaultdict[UUID, int] = defaultdict(int)

consolidation_locks: defaultdict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

reconcile_lock: asyncio.Lock = asyncio.Lock()

pending_consolidations: dict[UUID, asyncio.Task] = {}

@app.get("/health")
async def health(
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, bool]:
    db_ok = False
    if conn:
        try:
            await conn.fetchval("select 1")
            db_ok = True
        except Exception:
            db_ok = False
    return {"ok": True, "database_configured": db_ok}

async def save_or_reconcile(
    conn: asyncpg.Connection,
    content: str,
    embedding: list[float],    
) -> dict[str, str]:
    """Reconcile a new fact against similar existing memories.
    Returns the action taken and the id of the new memory or pending change."""
    async with reconcile_lock:
        similar = await memories.search_memories(
            conn, embedding, top_k=5, min_similarity=0.82
        )
        decision = await agent.reconcile_memory(content, similar)

        if decision["action"] == "ADD":
            memory_id = await memories.create_memory_db(conn, content, embedding)
            return {"action": "ADD", "memory_id": str(memory_id)}
        if decision["action"] == "SKIP":
            return {"action": "SKIP"}
        
        # REPLACE or DELETE - look up the target, saved as pending change
        target = next(
            (m for m in similar if str(m["id"]) == decision["target_id"]),
            None,
        )
        if target is None:
            memory_id = await memories.create_memory_db(conn, content, embedding)
            return {"action": "ADD", "memory_id": str(memory_id)}

        change_id = await memories.create_pending_change(
            conn,
            action=decision["action"],
            target_memory_id=UUID(decision["target_id"]),
            target_content=target["content"],
            proposed_content=content if decision["action"] == "REPLACE" else None,
        )
        return {"action": decision["action"], "change_id": str(change_id)}


async def consolidate_and_save(conversation_id: UUID) -> None:
    """Background task: extract facts rom unconsolidated messages via memory LLM,
    reconcile + save each, then mark the batch as consolidated."""
    if not database.pool:
        return

    async with consolidation_locks[conversation_id]:
        async with database.pool.acquire() as conn:
            messages = await fetch_unconsolidated_messages(conn, conversation_id)
            if not messages:
                return
            
            batch = [{"role": m["role"], "content": m["content"]} for m in messages]
            facts = await agent.consolidate_memories(batch)

            for fact in facts:
                embedding = await embeddings.get_provider().embed(fact)
                await save_or_reconcile(conn, fact, embedding)

            await update_last_consolidated(conn, conversation_id, messages[-1]["id"])

async def finalize_after(conversation_id: UUID, delay: float = 300) -> None:
    """Wait 'delay' seconds, then consolidate and summarize if idle and needed.
    Default delay is 5min (used by SSE disconnect). Startup recovery passes
    a shorter delay if the conversation was already idle for while."""
    if delay > 0:
        await asyncio.sleep(delay)

    #Someone reconnected during the wait -abort.
    if conversation_id in active_streams:
        return
    if not database.pool:
        return

    async with consolidation_locks[conversation_id]:
        async with database.pool.acquire() as conn:
            # Consolidation: catch any residual messages that never hit the 20 msg trigger.
            # Loop because fetch is capped at 50 — a large backlog needs multiple passes.
            while True:
                messages = await fetch_unconsolidated_messages(conn, conversation_id)
                if not messages:
                    break
                batch = [{"role": m["role"], "content": m["content"]} for m in messages]
                facts = await agent.consolidate_memories(batch)
                for fact in facts:
                    embedding = await embeddings.get_provider().embed(fact)
                    await save_or_reconcile(conn, fact, embedding)
                await update_last_consolidated(conn, conversation_id, messages[-1]["id"])

    # Summary doesn't need the consolidation lock — idempotent via `existing` check
    async with database.pool.acquire() as conn:
        existing = await conn.fetchval(
            """select summary 
            from conversations
            where id = $1""",
            conversation_id,
        )
        if existing:
            return

        full_history = await fetch_messages(conn, conversation_id)
        if not full_history:
            return

        summary = await agent.summarize_conversation(full_history)
        if not summary: 
            return

        await conn.execute(
            "update conversations set summary = $1 where id = $2",
            summary,
            conversation_id,
        )

async def recover_pending_finalizations() -> None:
    """On startup, schedule finalization for any conversation left mid-air.
    Delay = remaining time before the 5-min gate expires. If already past, delay=0."""
    if not database.pool:
        return
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            "select id, updated_at from conversations where summary is null"
        )
    now = datetime.now(timezone.utc)
    for row in rows:
        elapsed = (now - row["updated_at"]).total_seconds()
        remaining = max(0, 300 - elapsed)
        asyncio.create_task(finalize_after(row["id"], delay=remaining))

def schedule_consolidation(conversation_id: UUID, delay: float = 10) -> None:
    """Schedule consolidation for `delay` seconds from now. If another trigger
    arrives before then, the pending task is cancelled and rescheduled."""
    existing = pending_consolidations.get(conversation_id)
    if existing and not existing.done():
        existing.cancel()

    async def wait_and_run() -> None:
        try:
            await asyncio.sleep(delay)
            print(f"[debounce] consolidation firing for {conversation_id}")
            await consolidate_and_save(conversation_id)
        except asyncio.CancelledError:
            pass # Rescheduled by a fresh trigger
        finally:
            # Only pop if we're still the current pending task
            if pending_consolidations.get(conversation_id) is task:
                pending_consolidations.pop(conversation_id, None)

    task = asyncio.create_task(wait_and_run())
    pending_consolidations[conversation_id] = task
       
@app.post("/api/chat")
async def chat(
    payload: ChatRequest,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> StreamingResponse:
    conversation_id = payload.conversation_id
    history: list[dict[str, str]] = []
    relevant_memories: list[str] = []
    previous_summaries: list[str] = []

    if conn:
        if not conversation_id:
            conversation_id = await create_conversation(conn)
        elif not await conn.fetchval("select 1 from conversations where id = $1", conversation_id):
            await conn.execute("insert into conversations (id) values ($1)", conversation_id)
        # Fetch history BEFORE adding the new user message,
        # so the LLM doesn't see the new message as part of the history
        history = await fetch_messages(conn, conversation_id)
        await add_message(conn, conversation_id, "user", payload.message)
        # Inject ALL memories every turn. Cheap while the memory set is small;
        # see README "Smarter memory retrieval" for scaling strategies.
        memory_rows = await memories.list_memories_db(conn)
        relevant_memories = [m["content"] for m in memory_rows]
        previous_summaries = await fetch_conversation_summary(conn, conversation_id)
    else:
        conversation_id = conversation_id or uuid4()

    async def event_stream() -> AsyncIterator[str]:
        full = ""
        try:
            async for token in agent.stream_reply(
                payload.message,
                history=history,
                relevant_memories=relevant_memories,
                previous_summaries=previous_summaries,
            ):
                full += token
                yield token
        except asyncio.CancelledError:
            # Client aborted - don't save partial. Msg1 stays unanswered in DB
            raise
        else:
            # Reply completed normally - save it and fire consolidation.
            if full and database.pool:
                async with database.pool.acquire() as inner_conn:
                    await add_message(inner_conn, conversation_id, "assistant", full)
                    count = await get_unconsolidated_count(inner_conn, conversation_id)
                    if count > settings.consolidation_interval:
                        schedule_consolidation(conversation_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/plain",
        headers={"X-Conversation-Id": str(conversation_id)},
    )

@app.get("/api/greeting")
async def get_greeting() -> dict[str, str]:
    """Return the greeting generated at server startup.
    Empty string if warmup failed or no greeting is pending."""
    return {"greeting": startup_greeting}


@app.get("/api/conversations/latest", response_model=Conversation | None)
async def get_latest_conversation(
    conn: asyncpg.Connection | None = Depends(get_db),
) -> Conversation | None:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    row = await conn.fetchrow(
        "select id from conversations order by updated_at desc limit 1"
    )
    if not row:
        return None

    return await fetch_conversation(conn, row["id"])

@app.get("/api/conversations/active", response_model=Conversation | None)
async def get_active_conversation(
    conn: asyncpg.Connection | None = Depends(get_db),
) -> Conversation | None:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    #1. If any device is currently connected via SSe, return tha conversation
    if active_streams:
        conv_id = next(iter(active_streams))
        return await fetch_conversation(conn, conv_id)

    # 2. Grace Period: if the most-recent conversation was updated in the last 5min,
    # still count it as active so a reopen resumes it
    row = await conn.fetchrow(
        """
        select id from conversations
        where updated_at > now() - interval '5 minutes'
        order by updated_at desc
        limit 1
        """
    )
    if not row:
        return None
    return await fetch_conversation(conn, row["id"])

@app.get("/api/conversations/{conversation_id}/stream")
async def stream_conversation(conversation_id: UUID):
    """SSE stream of new messages for a conversation. Registers presence for the duration."""
    async def event_generator():
        active_streams[conversation_id] += 1
        try:
            last_seen = datetime.now(timezone.utc)
            while True:
                if not database.pool:
                    return

                async with database.pool.acquire() as conn:
                    rows = await conn.fetch(
                        """
                        select id, role, content, created_at
                        from messages
                        where conversation_id = $1 and created_at > $2
                        order by created_at asc
                        """,
                        conversation_id,
                        last_seen,
                    )
                for row in rows:
                    data = {
                        "id": str(row["id"]),
                        "role": row["role"],
                        "content": row["content"],
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                    last_seen = row["created_at"]

                # Heartbeat: SSE comment (line starting with :) is ignored by the browser
                # but forces a write, which fails and cancels the coroutine if the client
                # has disconnected - that's what triggers the finally block.
                yield ": keepalive\n\n"

                await asyncio.sleep(2)
        finally:
            active_streams[conversation_id] -= 1
            if active_streams[conversation_id] <= 0:
                del active_streams[conversation_id]
                #Schedule delayed summaization. If a device reconnects within 5 minutes
                # the task will see it in active_streams and skip
                asyncio.create_task(finalize_after(conversation_id))

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: UUID,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> Conversation:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    conversation = await fetch_conversation(conn, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation


@app.post("/api/memories")
async def create_memory(
    payload: MemoryCreateRequest,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, str]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    embedding = await embeddings.get_provider().embed(payload.content)
    return await save_or_reconcile(conn, payload.content, embedding)


@app.get("/api/memories", response_model=list[Memory])
async def list_memories(
    conn: asyncpg.Connection | None = Depends(get_db),
) -> list[dict]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    return await memories.list_memories_db(conn)


@app.delete("/api/memories/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, str]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    success = await memories.delete_memory_db(conn, memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"detail": "Memory deleted successfully"}

@app.get("/api/memory-changes", response_model=list[PendingMemoryChanges])
async def list_memory_changes(
    conn: asyncpg.Connection | None = Depends(get_db),
) -> list[dict]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    
    return await memories.list_pending_changes(conn)

@app.post("/api/memory-changes/{change_id}/approve")
async def approve_memory_change(
    change_id: UUID,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, str]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    
    change = await memories.get_pending_change(conn, change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="Pending change not found")


    if change["action"] == "REPLACE":
        new_content = change["proposed_content"]
        if not new_content:
            raise HTTPException(status_code=500, detail="REPLACE change has no proposed_content")
        new_embedding = await embeddings.get_provider().embed(new_content)
        await memories.update_memory_db(
            conn,
            change["target_memory_id"],
            new_content,
            new_embedding,
        )
    elif change["action"] == "DELETE":
        await memories.delete_memory_db(conn, change["target_memory_id"])

    await memories.delete_pending_change(conn, change_id)
    return {"detail": "Approved"}

@app.post("/api/memory-changes/{change_id}/skip")
async def skip_memory_change(
    change_id: UUID,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, str]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    deleted = await memories.delete_pending_change(conn, change_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Pending change not found")

    return {"detail": "Skipped"}


_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_CHARS = re.compile(r"[*_~`#>]+")
# Match "N-M" as a number range only when it's clearly standalone.
# Lookbehind/ahead exclude digits and hyphens so 2024-08-22, COVID-19,
# phone-like 555-1234, etc. are left alone.
_NUMBER_RANGE = re.compile(r"(?<![\d-])(\d{1,3})-(\d{1,3})(?![\d-])")

def strip_markdown_for_tts(text: str) -> str:
    """Rewrite text so Piper reads it as words, not symbols.
    Strips markdown formatting and rewrites simple number ranges."""
    text = _MARKDOWN_LINK.sub(r"\1", text)          # [label](url) -> label
    text = _MARKDOWN_CHARS.sub("", text)            # strip *, _, ~, `, #, >
    text = _NUMBER_RANGE.sub(r"\1 to \2", text)     # 1-4 -> "1 to 4"
    return text


@app.post("/api/speak")
async def speak(payload: SpeakRequest) -> Response:
    provider = voice.get_tts()
    clean_text = strip_markdown_for_tts(payload.text)
    audio_bytes = await provider.synthesize(clean_text)
    return Response(content=audio_bytes, media_type="audio/wav")


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict[str, str]:
    audio_bytes = await file.read()
    provider = voice.get_stt()
    text = await provider.transcribe(audio_bytes)
    return {"text": text}


