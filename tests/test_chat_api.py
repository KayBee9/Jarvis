import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import ChatRequest


async def send(message, conn, conversation_id=None):
    return await main.chat(ChatRequest(message=message, conversation_id=conversation_id), conn=conn)


def test_reply_streams_token_by_token_and_is_saved(fake_llm, fake_db):
    fake_llm.tokens = ["Hel", "lo"]

    async def scenario():
        response = await send("Hi", fake_db.conn)
        return [token async for token in response.body_iterator]

    assert asyncio.run(scenario()) == ["Hel", "lo"]
    assert fake_db.saved == [("user", "Hi"), ("assistant", "Hello")]


def test_user_message_is_saved_before_the_reply_starts(fake_llm, fake_db):
    asyncio.run(send("Hi", fake_db.conn))
    assert fake_db.saved == [("user", "Hi")]


def test_interrupted_reply_is_not_saved(fake_llm, fake_db):
    fake_llm.tokens = ["Hel", "lo"]

    async def scenario():
        response = await send("Hi", fake_db.conn)
        stream = response.body_iterator
        await anext(stream)
        with pytest.raises(asyncio.CancelledError):
            await stream.athrow(asyncio.CancelledError())

    asyncio.run(scenario())
    assert fake_db.saved == [("user", "Hi")]


def test_unanswered_message_is_merged_into_the_next_turn(fake_llm, fake_db):
    fake_db.history = [{"role": "user", "content": "How are you?"}]
    fake_llm.tokens = ["Fine"]

    async def scenario():
        response = await send("Get me chocolate", fake_db.conn)
        async for _ in response.body_iterator:
            pass

    asyncio.run(scenario())
    assert fake_llm.calls[0] == [{"role": "user", "content": "How are you?\n\nGet me chocolate"}]


def test_client_generated_id_is_kept_and_its_row_created(fake_llm, fake_db):
    conversation_id = uuid4()
    fake_db.conn.conversation_exists = False
    response = asyncio.run(send("Hi", fake_db.conn, conversation_id))
    assert response.headers["x-conversation-id"] == str(conversation_id)
    assert len(fake_db.conn.executed) == 1


@pytest.mark.parametrize(
    "count, fires",
    [
        (4, False),
        pytest.param(
            5,
            True,
            marks=pytest.mark.xfail(strict=True, reason="BUG: '>' fires one message after the interval"),
        ),
        (6, True),
    ],
)
def test_consolidation_trigger_threshold(fake_llm, fake_db, monkeypatch, count, fires):
    monkeypatch.setattr(main.settings, "consolidation_interval", 5)
    fake_db.count = count
    fake_llm.tokens = ["Hi"]

    async def scenario():
        response = await send("Hi", fake_db.conn)
        async for _ in response.body_iterator:
            pass

    asyncio.run(scenario())
    assert bool(fake_db.scheduled) is fires


def test_chat_over_http_exposes_the_conversation_id_to_the_browser(fake_llm):
    fake_llm.tokens = ["Hel", "lo"]
    response = TestClient(main.app).post(
        "/api/chat",
        json={"message": "Hi"},
        headers={"Origin": main.settings.frontend_origin},
    )
    assert response.status_code == 200
    assert response.text == "Hello"
    assert response.headers["x-conversation-id"]
    assert "x-conversation-id" in response.headers["access-control-expose-headers"].lower()


def test_speak_cleans_text_before_sending_it_to_tts(monkeypatch):
    spoken = []

    async def synthesize(text):
        spoken.append(text)
        return b"wav-bytes"

    monkeypatch.setattr(main.voice, "get_tts", lambda: SimpleNamespace(synthesize=synthesize))
    response = TestClient(main.app).post("/api/speak", json={"text": "*Rest* for 1-4 days"})
    assert spoken == ["Rest for 1 to 4 days"]
    assert response.content == b"wav-bytes"
    assert response.headers["content-type"] == "audio/wav"
