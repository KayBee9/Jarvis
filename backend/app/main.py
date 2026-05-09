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


settings = get_settings()
app = FastAPI(title="Jarvis API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await database.connect()


@app.on_event("shutdown")
async def shutdown() -> None:
    await database.close()


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
