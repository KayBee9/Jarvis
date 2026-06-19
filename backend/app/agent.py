from typing import Protocol

import json
import anthropic
from ollama import AsyncClient as OllamaClient

from app.config import get_settings

SYSTEM_PROMPT = """
You are Jarvis, a personal assistant for one specific user named Oscar.

Hard rules — never break these:
- You have NO access to a calendar, email, files, weather, browser, or any tools.
  You only have what's in this prompt and what the user types.
- Do NOT invent facts about the user — their schedule, contacts, projects,
  preferences, habits, history, or anything else.
- If asked "what do you know about me," answer ONLY from facts explicitly listed
  in the "Facts about the user" section below. If that section is missing or empty,
  say "Nothing yet — you haven't shared anything I've saved."
- If you don't know something, say so. Don't guess and don't fill silence.

Style:
- Concise and direct. Skip pleasantries unless the user opens with one.
- Match the user's tone — formal if they're formal, casual if they're casual.
- One sentence is often enough. Don't pad answers to feel helpful.
""".strip()


EXTRACTION_PROMPT = """
You are a fact extractor.

Look at the user message below. Identify any DURABLE facts the user has stated
about themselves — things that will still be true tomorrow.

Categories that count:
- Preferences (food, music, work style, hobbies)
- Biographical details (name, age, location, job, education)
- Relationships (family, friends, pets, partners)
- Ongoing goals or situations (a project they're working on, a habit they have)

Categories that do NOT count:
- One-time events ("I went to the store today")
- Questions or requests ("Can you help me with X?")
- Opinions about the conversation itself
- Facts about other people (only the user)

Rules:
- Only extract facts the user has STATED about themselves
- Do not infer, guess, or fill in gaps
- Phrase each fact concisely in third person and start with the user's name, which is Oscar. An example would be "Oscar prefers tea over coffee"
- If no qualifying facts are present, return an empty array

Return ONLY valid JSON in this exact shape:
{"facts": ["fact 1", "fact 2"]}
""".strip()

class LLMProvider(Protocol):
    """Common interface for LLM backend"""

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]], 
    ) -> str: ...

class OllamaProvider:
    """Local LLM via Ollama's HTTP API"""

    def __init__(self, model: str, base_url: str) -> None:
        self._model = model
        self._client = OllamaClient(host=base_url)

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        response = await self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                *messages,
            ],
        )
        return response["message"]["content"]
    
class AnthropicProvider:
    """Cloud LLM via Anthropic's Claude API."""

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text
    
_provider: LLMProvider | None = None

def init__provider() -> LLMProvider:
    """Initialize the LLM provider based on config settings. Call once at startup."""

    global _provider
    settings = get_settings()
    if settings.llm_provider == "ollama":
        _provider = OllamaProvider(model=settings.ollama_model, base_url=settings.ollama_base_url)
    elif settings.llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key is required for Anthropic provider")
        _provider = AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    else:
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
    return _provider

def get_provider() -> LLMProvider:
    if _provider is None:
        raise ValueError("LLM provider not initialized.")
    return _provider

async def generate_reply(
        message: str, 
        history: list[dict[str, str]],
        relevant_memories: list[str] | None = None,
    ) -> str:
    """Build a system prompt with relevant memories, append the user message, call the LLM"""
    system_prompt = SYSTEM_PROMPT
    if relevant_memories:
        facts = "\n".join(f"- {mem}" for mem in relevant_memories)
        system_prompt += f"\n\nFacts you know about the user:\n{facts}"

    messages = [*history, {"role": "user", "content": message}]
    return await get_provider().generate(system_prompt=system_prompt, messages=messages)

import re

async def extract_memories(message: str) -> list[str]:
    """Run a second LLM call to find durable facts about use"""
    try: 
        response = await get_provider().generate(
            EXTRACTION_PROMPT,
            [{"role": "user", "content": message}],
        )
        # Find the first {...} block anywhere in the response
        match = re.search(r"\{[\s\S]*\}", response)
        if not match:
            return []
        data = json.loads(match.group(0))
        facts = data.get("facts", [])
        print(facts)
        return [f.strip() for f in facts if isinstance(f, str) and f.strip()]

    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        # Extraction is best-effort - if the LLM returns garbage, just skip
        return []