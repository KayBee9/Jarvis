import asyncio

import pytest

from app import agent

pytestmark = pytest.mark.eval


@pytest.fixture(autouse=True)
def real_llm(monkeypatch):
    monkeypatch.setattr(agent, "_provider", None)
    monkeypatch.setattr(agent, "_memory_provider", None)
    agent.init_provider()


def extract(text):
    return asyncio.run(agent.consolidate_memories([{"role": "user", "content": text}]))


@pytest.mark.parametrize(
    "new_fact, existing, action",
    [
        ("Oscar likes Lenovo laptops", "Oscar likes laptops", "ADD"),
        ("Oscar's favorite pie flavor is apple", "Oscar likes pies", "ADD"),
        ("Oscar likes chocolate", "Oscar likes meat", "ADD"),
        ("Oscar plays tennis", "Oscar plays football", "ADD"),
        ("Oscar enjoys drinking coffee", "Oscar likes coffee", "SKIP"),
        ("Oscar has moved to Madrid", "Oscar lives in Lisbon", "REPLACE"),
        ("Oscar no longer drinks coffee", "Oscar drinks coffee", "DELETE"),
        ("Oscar does not like Macbooks", "Oscar especially prefers Macbooks", "DELETE"),
    ],
)
def test_reconciler_decision(new_fact, existing, action):
    similar = [{"id": "11111111-1111-1111-1111-111111111111", "content": existing}]
    assert asyncio.run(agent.reconcile_memory(new_fact, similar))["action"] == action


def test_sibling_facts_are_extracted_separately():
    facts = " | ".join(extract("I like chocolate and meat")).lower()
    assert "chocolate" in facts and "meat" in facts
    assert "|" in facts


@pytest.mark.parametrize(
    "text",
    [
        "How's the weather? Also can you remind me tomorrow?",
        "Can you tell me about smart home automation?",
        "Actually, I was wrong about that.",
    ],
)
def test_questions_and_chatter_produce_no_facts(text):
    assert extract(text) == []
