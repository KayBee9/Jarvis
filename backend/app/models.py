from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    conversation_id: UUID
    assistant_message: str


class Message(BaseModel):
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class Conversation(BaseModel):
    id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[Message]

class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)

class Memory(BaseModel):
    id: UUID
    content: str
    created_at: datetime

class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)