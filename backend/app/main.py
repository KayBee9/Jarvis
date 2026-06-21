from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import agent, embeddings, memories, voice
from app.config import get_settings
from app.db import (
    add_message,
    create_conversation,
    database,
    fetch_conversation,
    get_db,
    fetch_messages,
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
)


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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    conn: asyncpg.Connection | None = Depends(get_db),
) -> ChatResponse:
    conversation_id = payload.conversation_id
    history: list[dict[str, str]] = []
    relevant_memories: list[str] = []

    if conn:
        if not conversation_id:
            conversation_id = await create_conversation(conn)
        # Fetch history BEFORE adding the new user message,
        # so the LLM doesn't see the new message as part of the history
        history = await fetch_messages(conn, conversation_id)
        await add_message(conn, conversation_id, "user", payload.message)
        # Inject ALL memories every turn. Cheap while the memory set is small;
        # see README "Smarter memory retrieval" for scaling strategies.
        memory_rows = await memories.list_memories_db(conn)
        relevant_memories = [m["content"] for m in memory_rows]
    else:
        conversation_id = conversation_id or uuid4()

    assistant_message = await agent.generate_reply(
        payload.message,
        history=history,
        relevant_memories=relevant_memories,
    )

    if conn:
        await add_message(
            conn,
            conversation_id,
            "assistant",
            assistant_message,
        )
        # Extract durable facts from the user#s message and saves them automatically
        extracted_facts = await agent.extract_memories(payload.message)
        for fact in extracted_facts:
            fact_embedding = await embeddings.get_provider().embed(fact)
            
            #Find similar existing memories to reconcile against.
            similar = await memories.search_memories(
                conn, fact_embedding, top_k=5, min_similarity=0.5
            )

            #Ask the LLM how to handle this fact
            decision = await agent.reconcile_memory(fact, similar)

            if decision["action"] == "ADD":
                await memories.create_memory_db(conn, fact, fact_embedding)
            elif decision["action"] == "SKIP":
                pass
            elif decision["action"] in ("REPLACE","DELETE"):
                # Find the target's current content for the snapshot
                target = next(
                    (m for m in similar if str(m["id"]) == decision["target_id"]),
                    None,
                )
                if target is None:
                    continue #safety: target not in similar list, something went wrong
                await memories.create_pending_change(
                    conn,
                    action=decision["action"],
                    target_memory_id=UUID(decision["target_id"]),
                    target_content=target["content"],
                    proposed_content=fact if decision["action"] == "REPLACE" else None,
                )

    return ChatResponse(
        conversation_id=conversation_id,
        assistant_message=assistant_message,
    )


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
    memory_id = await memories.create_memory_db(conn, payload.content, embedding)
    return {"memory_id": str(memory_id)}


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


@app.post("/api/speak")
async def speak(payload: SpeakRequest) -> Response:
    provider = voice.get_tts()
    audio_bytes = await provider.synthesize(payload.text)
    return Response(content=audio_bytes, media_type="audio/wav")


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict[str, str]:
    audio_bytes = await file.read()
    provider = voice.get_stt()
    text = await provider.transcribe(audio_bytes)
    return {"text": text}