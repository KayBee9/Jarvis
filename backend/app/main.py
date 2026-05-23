from typing import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import agent
from app import memories
from app import embeddings
from app.auth import get_current_user_id
from app.config import get_settings
from app.db import (
    add_message,
    create_conversation,
    database,
    fetch_conversation,
    get_db,
    get_previous_response_id,
)

from app.models import ChatRequest, ChatResponse, Conversation, MemoryCreateRequest, Memory

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await database.connect()
    embeddings.init_provider() #loads the embedding model at startup
    yield
    await database.close()


settings = get_settings()
app = FastAPI(title="Jarvis API", version="0.1.0", lifespan=lifespan)

#Runs before and after each request from a stack, meaning last in this list runs first before the request
# and first in this list first after the request (5,4,3,2,1,request, response, 1,2,3,4,5)
app.add_middleware(
    CORSMiddleware, #1
    allow_origins=[settings.frontend_origin], #2 
    allow_credentials=True, #3 
    allow_methods=["*"], #4 (allow all HTTP methods)
    allow_headers=["*"], #5 (allow all HTTP headers)
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
    user_id: str = Depends(get_current_user_id),
    conn: asyncpg.Connection | None = Depends(get_db),
) -> ChatResponse:
    conversation_id = payload.conversation_id
    previous_response_id = None

    if conn:
        if not conversation_id:
            conversation_id = await create_conversation(conn, user_id)
        previous_response_id = await get_previous_response_id(conn, conversation_id, user_id)
        await add_message(conn, conversation_id, user_id, "user", payload.message)
        query_embedding = await embeddings.get_provider().embed(payload.message)
        memory_rows = await memories.search_memories(conn, user_id, query_embedding)
        relevant_memories = [memory["content"] for memory in relevant_memories]
    else:
        conversation_id = conversation_id or uuid4()

    assistant_message, response_id = await agent.generate_reply(
        payload.message,
        previous_response_id=previous_response_id,
        relevant_memories=relevant_memories
    )

    if conn:
        await add_message(
            conn,
            conversation_id,
            user_id,
            "assistant",
            assistant_message,
            response_id=response_id,
        )

    return ChatResponse(
        conversation_id=conversation_id,
        assistant_message=assistant_message,
        response_id=response_id,
    )


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: asyncpg.Connection | None = Depends(get_db),
) -> Conversation:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    conversation = await fetch_conversation(conn, conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation

@app.post("/api/memories")
async def create_memory(
    payload: MemoryCreateRequest,
    user_id: str = Depends(get_current_user_id),
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, str]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    
    embedding = await embeddings.get_provider().embed(payload.content)
    memory_id = await memories.create_memory_db(conn, user_id, payload.content, embedding)
    return {"memory_id": str(memory_id)}

@app.get("/api/memories", response_model=list[Memory])
async def list_memories(
    user_id: str = Depends(get_current_user_id),
    conn: asyncpg.Connection | None = Depends(get_db),
) -> list[dict]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    return await memories.list_memories_db(conn, user_id)

@app.delete("/api/memories/{memory_id}")
async def delete_memory(
    memory_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: asyncpg.Connection | None = Depends(get_db),
) -> dict[str, str]:
    if not conn:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    success = await memories.delete_memory_db(conn, user_id, memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"detail": "Memory deleted successfully"}
