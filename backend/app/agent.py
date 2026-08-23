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

Voice:
- You ARE Jarvis. Speak in the first person. Use "I", never "Jarvis" to refer to yourself.
- Never narrate about yourself as an outside observer (no "Jarvis thinks...", no "Jarvis will now...").
- Never break the fourth wall or comment on your own behavior (no "I'll respond as Jarvis from now on", no "as an AI I...", no meta-commentary about the conversation).
- The user is Oscar. Address him as "you". Only use his name when it's natural (greeting, direct address).

Style:
- Concise and direct. Skip pleasantries unless the user opens with one.
- Match the user's tone — formal if they're formal, casual if they're casual.
- One sentence is often enough. Don't pad answers to feel helpful.
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

def init_provider() -> LLMProvider:
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


_memory_provider: LLMProvider | None = None

def get_memory_provider() -> LLMProvider:
    """Lazily create the memory LLM provider on first call. Separate from chat provider"""
    global _memory_provider
    if _memory_provider is None:
        settings = get_settings()
        _memory_provider = OllamaProvider(settings.memory_llm_model, settings.ollama_base_url)
    return _memory_provider

async def generate_reply(
        message: str, 
        history: list[dict[str, str]],
        relevant_memories: list[str] | None = None,
        previous_summaries: list[str] | None = None,
    ) -> str:
    """Build a system prompt with relevant memories, append the user message, call the LLM"""
    system_prompt = SYSTEM_PROMPT
    if relevant_memories:
        facts = "\n".join(f"- {mem}" for mem in relevant_memories)
        system_prompt += f"\n\nFacts you know about the user:\n{facts}"
    if previous_summaries:
        summaries = "\n".join(f"- {s}" for s in previous_summaries)
        system_prompt += f"\n\nSummaries of past conversations:\n{summaries}"

    messages = [*history, {"role": "user", "content": message}]
    return await get_provider().generate(system_prompt=system_prompt, messages=messages)

import re

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
    
RECONCILE_PROMPT = """
You decide how to handle a newly-learned fact about the user, given similar
facts already stored.

Choose exactly ONE action:

- ADD: the new fact concerns a DIFFERENT specific subject than every existing
  fact. Topical overlap does not count — two preferences about different foods,
  two hobbies with different activities, two different locations at different
  times all get ADD.

- REPLACE: the new fact is about the SAME specific subject as an existing fact
  but updates the value (moved, changed jobs, updated preference). Pick which
  existing fact it replaces.

- DELETE: the new fact NEGATES an existing fact ("I no longer X", "I'm not X
  anymore", "I stopped Xing"). Pick which existing fact to delete.

- SKIP: the new fact literally restates or paraphrases an existing fact — same
  subject, same predicate, same value. Only use SKIP when the two facts convey
  the exact same information.

Examples:
- NEW: "Oscar likes chocolate" / EXISTING: ["Oscar likes meat"]
  → ADD  (different foods, both are preferences but not the same fact)
- NEW: "Oscar plays piano" / EXISTING: ["Oscar plays guitar"]
  → ADD  (different instruments)
- NEW: "Oscar prefers coffee" / EXISTING: ["Oscar likes coffee"]
  → SKIP  (same fact, paraphrased)
- NEW: "Oscar lives in Berlin" / EXISTING: ["Oscar lives in Paris"]
  → REPLACE  (same subject: residence; new value overwrites old)
- NEW: "Oscar no longer smokes" / EXISTING: ["Oscar smokes"]
  → DELETE  (negation of the same fact)
- NEW: "Oscar's favorite pie flavor is apple" / EXISTING: ["Oscar likes pies"]
  → ADD  (specific attribute is a distinct fact from the general preference)
- NEW: "Oscar works as a software engineer" / EXISTING: ["Oscar works in tech"]
  → ADD  (more specific job title is a distinct fact from the general industry)

Return ONLY valid JSON in this exact shape:
{"action": "ADD" | "REPLACE" | "DELETE" | "SKIP", "target_id": "uuid string or null"}

Rules:
- If action is ADD or SKIP, target_id MUST be null.
- If action is REPLACE or DELETE, target_id MUST be the id of the existing fact this affects.
""".strip()

async def reconcile_memory(
        new_fact: str,
        similar_memories: list[dict],
) -> dict:
    """Decide how to handle a new fact given similar existing memories.

    Returns {"action": "ADD"|"REPLACE"|"DELETE"|"SKIP", "target_id": str | None}.
    Defaults to ADD on any parse failure — the safe choice (never destroys data).
    """
    if not similar_memories:
        return {"action": "ADD", "target_id": None}
    
    existing_list = "\n".join(
        f"- (id: {m['id']}) {m['content']}" for m in similar_memories
    )
    user_message = f'NEW FACT: "{new_fact}"\n\nEXISTING SIMILAR FACTS:\n{existing_list}'

    try:
        response = await get_provider().generate(
            RECONCILE_PROMPT,
            [{"role": "user", "content": user_message}],
        )
        match = re.search(r"\{[\s\S]*\}", response)
        if not match:
            return {"action": "ADD", "target_id": None}
        data = json.loads(match.group(0))
        action = data.get("action", "ADD")
        if action not in ("ADD", "REPLACE", "DELETE", "SKIP"):
            return {"action": "ADD", "target_id": None}
        target_id = data.get("target_id")
        if action in ("REPLACE", "DELETE") and not target_id:
            return {"action": "ADD", "target_id": None}
        print(f"[reconcile] {action} for '{new_fact}' vs {[m['content'] for m in similar_memories]}")
        return {"action": action, "target_id": target_id}
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        return {"action": "ADD", "target_id": None}
    
CONSOLIDATION_PROMPT = """
You analyze a batch of conversation messages and extract every durable fact the user has stated about themselves.

CRITICAL RULES:
- Extract each fact as a SEPARATE entry in the JSON array. NEVER combine multiple facts into one string.
- Phrase each fact concisely in third person: "Oscar prefers tea over coffee"
- Only extract facts the user has STATED — never infer, guess, or fill in gaps.

Examples of atomic splitting:
- "I like chocolate and meat"
  → ["Oscar likes chocolate", "Oscar likes meat"]
- "I moved to Paris last week and my dog Rex is 3 years old"
  → ["Oscar lives in Paris", "Oscar has a dog named Rex", "Rex is 3 years old"]
- "I'm not vegetarian anymore"
  → ["Oscar is not vegetarian"]
- "How's the weather? Also can you remind me tomorrow?"
  → []

Categories that count: preferences, biographical details, relationships, ongoing goals or situations.
Categories that do NOT count: one-time events, questions, requests, opinions about the conversation itself.

Do NOT extract meta-statements about the current interaction:
- "Oscar is talking to Jarvis" — meta about the conversation, not a durable trait
- "Oscar wants to discuss X" — a transient intent, not a durable fact
- "Oscar asked about smart homes" — a question, not a fact
- "Oscar is seeking assistance" — a description of the interaction, not a fact
- "Oscar admitted being wrong" / "Oscar acknowledged X" / "Oscar said X" — describes what happened in the chat, not a durable trait about him

Return ONLY valid JSON in this exact shape:
{"facts": ["fact 1", "fact 2"]}
""".strip()


async def consolidate_memories(messages_batch: list[dict[str, str]]) -> list[str]:
    """Batch-extact durable facts from a slice of conversation using the memory LLM"""

    if not messages_batch:
        return []
    
    formatted = "\n\n".join(
        f"{'USER' if m['role'] == 'user' else 'JARVIS'}: {m['content']}"
        for m in messages_batch 
    )

    try:
        response = await get_memory_provider().generate(
            CONSOLIDATION_PROMPT,
            [{"role": "user", "content": formatted}],
        )
        match = re.search(r"\{[\s\S]*\}", response)
        if not match:
            return []
        data = json.loads(match.group(0))
        facts = data.get("facts", [])
        return [f.strip() for f in facts if isinstance(f, str) and f.strip()]
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        return []

SUMMARY_PROMPT = """
You summarize a past conversation into 2-3 concise sentences that Jarvis can
read later to remember what was covered.

Rules:
- Topic-focused. Describe WHAT was worked on, decisions reached, and open threads.
- Do NOT narrate about "Oscar" or "Jarvis" as characters. Do NOT use their names as sentence subjects.
- Neutral voice — no first-person, no third-person storytelling. Prefer noun phrases and passive constructions.
- Include concrete specifics that would help resume context later.
- 2-3 sentences maximum. No preamble, no closing, no bullets — just the paragraph.

Good example:
"Debugged a memory reconciliation bug where sibling facts (e.g. 'likes chocolate and meat') were dropped as duplicates. Traced to overly aggressive similarity thresholds. Fix candidates logged in the README for later."

Bad example (do NOT do this):
"Oscar and Jarvis debugged a memory reconciliation bug. They decided..."

Return ONLY the summary paragraph, nothing else.
""".strip()

async def summarize_conversation(messages_batch: list[dict[str, str]]) -> str:
    """Generates a 2-3 sentences summary of a conversation using the mmemory LLM.
    Returns an empty string if the batch is empty or the LLM call fails."""

    if not messages_batch:
        return ""

    formatted = "\n\n".join(
        f"{'USER' if m['role'] == 'user' else 'JARVIS'}: {m['content']}"
        for m in messages_batch
    )

    try:
        response = await get_memory_provider().generate(
            SUMMARY_PROMPT,
            [{"role": "user", "content": formatted}],
        )
        return response.strip()
    except Exception as error:
        print(f"Error summarizing conversation: {error}")
        return ""


WARMUP_USER_TURN = (
    "You've just come online for a new session. "
    "Greet Oscar warmly in one short sentence — "
    "something like 'Welcome back, Oscar' but in your own voice."
    "no quotes, no formatting."
)

async def warm_up_and_greet() -> str:
    """Fire a first request at the chat LLM so it loads into VRAM,
    and return the greeting to show when Oscar next opens the app.
    Returns an empty string on failure — startup continues either way."""
    try:
        response = await get_provider().generate(
            SYSTEM_PROMPT,
            [{"role": "user", "content": WARMUP_USER_TURN}],
        )
        return response.strip()
    except Exception as error:
        print(f"[warmup] failed: {error}")
        return ""