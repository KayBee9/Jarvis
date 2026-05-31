from uuid import UUID
from xmlrpc import client

import anthropic

from app.config import get_settings


SYSTEM_PROMPT = """
You are Jarvis, a warm, practical personal assistant.
For Phase 1, focus on natural text conversation only.
Do not claim you can remember, create reminders, or use voice yet.
If the user asks for those future capabilities, explain that they are planned.
Keep answers concise, useful, and conversational.
""".strip()

DEV_RESPONSES = {
    "hello": "Hey! I'm Jarvis. How can I help you today?",
    "i am enzo": "Fuck you Enzo",
    "what can you do": "Right now I can respond to certain keywords",
    "weather": "I don't have weather access yet — that's planned for a future phase.",
}

async def generate_reply(message: str, previous_response_id: str | None = None,
                        relevant_memories: list[str] | None = None) -> tuple[str, str | None]:
    settings = get_settings()

    if not settings.anthropic_api_key:
        reply = next(
            (response for keyword, response in DEV_RESPONSES.items() if keyword in message.lower()),
            f"I can chat in local dev mode, but I am not connected to Anthropic yet"
        )
        return reply, None
        # return (
        #     "I can chat in local dev mode, but I am not connected to OpenAI yet. "
        #     "Set OPENAI_API_KEY in backend/.env and restart the FastAPI server for full responses. "
        #     f"You said: {message}",
        #     None,
        # )

    system_prompt = SYSTEM_PROMPT
    if relevant_memories:
        memories = "\n".join(f"- {memory}" for memory in relevant_memories)
        system_prompt += f"\n\nHere are some relevant memories to consider:\n{memories}" #Maybe need to change this for better results

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text, response.id


def fallback_conversation_id(seed: UUID | None) -> UUID | None:
    return seed
