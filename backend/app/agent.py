from uuid import UUID

from openai import AsyncOpenAI

from app.config import get_settings


SYSTEM_PROMPT = """
You are Jarvis, a warm, practical personal assistant.
For Phase 1, focus on natural text conversation only.
Do not claim you can remember, create reminders, or use voice yet.
If the user asks for those future capabilities, explain that they are planned.
Keep answers concise, useful, and conversational.
""".strip()


async def generate_reply(message: str, previous_response_id: str | None = None) -> tuple[str, str | None]:
    settings = get_settings()

    if not settings.openai_api_key:
        return (
            "I can chat in local dev mode, but I am not connected to OpenAI yet. "
            "Set OPENAI_API_KEY in backend/.env and restart the FastAPI server for full responses. "
            f"You said: {message}",
            None,
        )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    request = {
        "model": settings.openai_model,
        "instructions": SYSTEM_PROMPT,
        "input": message,
    }
    if previous_response_id:
        request["previous_response_id"] = previous_response_id

    response = await client.responses.create(**request)

    return response.output_text, response.id


def fallback_conversation_id(seed: UUID | None) -> UUID | None:
    return seed
