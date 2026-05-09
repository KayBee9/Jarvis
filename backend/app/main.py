from typing import AsyncIterator
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import agent
from app.auth import get_current_user_id
from app.config import get_settings
from app.db import (
    add_message,
    create_conversation,
    database,
    fetch_conversation,
    get_previous_response_id,
)
from app.models import ChatRequest, ChatResponse, Conversation

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await database.connect()
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
async def health() -> dict[str, bool]:
    return {"ok": True, "database_configured": database.is_configured}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user_id: str = Depends(get_current_user_id),
) -> ChatResponse:
    conversation_id = payload.conversation_id
    previous_response_id = None

    if database.is_configured:
        if not conversation_id:
            conversation_id = await create_conversation(user_id)
        previous_response_id = await get_previous_response_id(conversation_id, user_id)
        await add_message(conversation_id, user_id, "user", payload.message)
    else:
        conversation_id = conversation_id or uuid4()

    assistant_message, response_id = await agent.generate_reply(
        payload.message,
        previous_response_id=previous_response_id,
    )

    if database.is_configured:
        await add_message(
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
) -> Conversation:
    if not database.is_configured:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")

    conversation = await fetch_conversation(conversation_id, user_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation
