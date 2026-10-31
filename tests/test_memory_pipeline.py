import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import main

TARGET_ID = str(uuid4())
SIMILAR = [{"id": TARGET_ID, "content": "Oscar lives in Paris"}]


@pytest.fixture
def store(monkeypatch):
    state = SimpleNamespace(created=[], pending=[])

    async def search_memories(conn, embedding, top_k, min_similarity):
        return SIMILAR

    async def create_memory_db(conn, content, embedding):
        state.created.append(content)
        return uuid4()

    async def create_pending_change(conn, action, target_memory_id, target_content, proposed_content):
        state.pending.append((action, proposed_content))
        return uuid4()

    monkeypatch.setattr(main.memories, "search_memories", search_memories)
    monkeypatch.setattr(main.memories, "create_memory_db", create_memory_db)
    monkeypatch.setattr(main.memories, "create_pending_change", create_pending_change)
    return state


def reconcile(fake_llm, reply):
    fake_llm.reply = reply
    return asyncio.run(main.save_or_reconcile(None, "Oscar lives in Berlin", [0.1]))


def test_add_saves_the_fact(fake_llm, store):
    reconcile(fake_llm, '{"action": "ADD", "target_id": null}')
    assert store.created == ["Oscar lives in Berlin"]
    assert store.pending == []


def test_skip_saves_nothing(fake_llm, store):
    reconcile(fake_llm, '{"action": "SKIP", "target_id": null}')
    assert store.created == []
    assert store.pending == []


def test_replace_waits_for_approval(fake_llm, store):
    reconcile(fake_llm, f'{{"action": "REPLACE", "target_id": "{TARGET_ID}"}}')
    assert store.created == []
    assert store.pending == [("REPLACE", "Oscar lives in Berlin")]


def test_delete_waits_for_approval(fake_llm, store):
    reconcile(fake_llm, f'{{"action": "DELETE", "target_id": "{TARGET_ID}"}}')
    assert store.created == []
    assert store.pending == [("DELETE", None)]


def test_unknown_target_falls_back_to_add(fake_llm, store):
    reconcile(fake_llm, '{"action": "DELETE", "target_id": "made-up-id"}')
    assert store.created == ["Oscar lives in Berlin"]
    assert store.pending == []


@pytest.fixture
def consolidation(monkeypatch, fake_db):
    state = SimpleNamespace(saved_facts=[], pointer=None)
    last_message_id = uuid4()

    async def fetch_unconsolidated_messages(conn, conversation_id):
        return [{"id": last_message_id, "role": "user", "content": "I like tea"}]

    async def update_last_consolidated(conn, conversation_id, message_id):
        state.pointer = message_id

    async def save_or_reconcile(conn, fact, embedding):
        state.saved_facts.append(fact)

    async def embed(text):
        return [0.1]

    monkeypatch.setattr(main, "fetch_unconsolidated_messages", fetch_unconsolidated_messages)
    monkeypatch.setattr(main, "update_last_consolidated", update_last_consolidated)
    monkeypatch.setattr(main, "save_or_reconcile", save_or_reconcile)
    monkeypatch.setattr(main.embeddings, "get_provider", lambda: SimpleNamespace(embed=embed))
    state.last_message_id = last_message_id
    return state


def test_consolidation_saves_facts_and_advances_the_pointer(fake_llm, consolidation):
    fake_llm.reply = '{"facts": ["Oscar likes tea"]}'
    asyncio.run(main.consolidate_and_save(uuid4()))
    assert consolidation.saved_facts == ["Oscar likes tea"]
    assert consolidation.pointer == consolidation.last_message_id


def test_a_batch_with_no_facts_still_advances_the_pointer(fake_llm, consolidation):
    fake_llm.reply = '{"facts": []}'
    asyncio.run(main.consolidate_and_save(uuid4()))
    assert consolidation.pointer == consolidation.last_message_id


@pytest.mark.xfail(strict=True, reason="BUG: garbage LLM output advances the pointer, so those facts are lost")
def test_failed_extraction_keeps_the_messages_for_a_retry(fake_llm, consolidation):
    fake_llm.reply = "not json at all"
    asyncio.run(main.consolidate_and_save(uuid4()))
    assert consolidation.pointer is None
