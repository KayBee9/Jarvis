import asyncio

import pytest

from app.agent import consolidate_memories, reconcile_memory

SIMILAR = [{"id": "abc-123", "content": "Oscar likes tea"}]
BATCH = [{"role": "user", "content": "I like tea"}]
ADD = {"action": "ADD", "target_id": None}


@pytest.mark.parametrize(
    "reply, expected",
    [
        ('{"action": "SKIP", "target_id": null}', {"action": "SKIP", "target_id": None}),
        ('{"action": "REPLACE", "target_id": "abc-123"}', {"action": "REPLACE", "target_id": "abc-123"}),
        ('{"action": "DELETE", "target_id": "abc-123"}', {"action": "DELETE", "target_id": "abc-123"}),
        ('Sure! {"action": "SKIP", "target_id": null} Done.', {"action": "SKIP", "target_id": None}),
    ],
)
def test_reconciler_reads_valid_decisions(fake_llm, reply, expected):
    fake_llm.reply = reply
    assert asyncio.run(reconcile_memory("Oscar drinks tea", SIMILAR)) == expected


@pytest.mark.parametrize(
    "reply",
    [
        "I am not sure",
        "{broken json}",
        '{"action": "MERGE", "target_id": null}',
        '{"action": "REPLACE", "target_id": null}',
        '{"action": "DELETE"}',
    ],
)
def test_reconciler_falls_back_to_add_because_it_never_destroys_data(fake_llm, reply):
    fake_llm.reply = reply
    assert asyncio.run(reconcile_memory("Oscar drinks tea", SIMILAR)) == ADD


def test_reconciler_skips_the_llm_when_nothing_is_similar(fake_llm):
    assert asyncio.run(reconcile_memory("Oscar drinks tea", [])) == ADD
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "reply, facts",
    [
        ('{"facts": ["Oscar likes tea", "Oscar likes cake"]}', ["Oscar likes tea", "Oscar likes cake"]),
        ('Here you go: {"facts": ["Oscar likes tea"]}', ["Oscar likes tea"]),
        ('{"facts": ["  Oscar likes tea  ", "   ", 42]}', ["Oscar likes tea"]),
        ('{"facts": []}', []),
        ("no json here", []),
        ("{broken json}", []),
    ],
)
def test_extractor_reads_facts(fake_llm, reply, facts):
    fake_llm.reply = reply
    assert asyncio.run(consolidate_memories(BATCH)) == facts


def test_extractor_skips_the_llm_for_an_empty_batch(fake_llm):
    assert asyncio.run(consolidate_memories([])) == []
    assert fake_llm.calls == []


@pytest.mark.xfail(strict=True, reason="BUG: a string under 'facts' is split into single characters")
def test_extractor_does_not_split_a_string_into_characters(fake_llm):
    fake_llm.reply = '{"facts": "Oscar likes tea"}'
    assert asyncio.run(consolidate_memories(BATCH)) in ([], ["Oscar likes tea"])


@pytest.mark.xfail(strict=True, reason="BUG: TypeError isn't caught, so null under 'facts' crashes extraction")
def test_extractor_survives_null_facts(fake_llm):
    fake_llm.reply = '{"facts": null}'
    assert asyncio.run(consolidate_memories(BATCH)) == []
