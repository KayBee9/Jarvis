import os

# Must run before any app import: overrides DATABASE_URL from .env so no test can reach real data.
os.environ["DATABASE_URL"] = ""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import agent, main
from app.config import get_settings
from app.db import database


@pytest.fixture(scope="session", autouse=True)
def never_touch_the_real_database():
    assert not get_settings().database_url
    assert database.pool is None


class FakeLLM:
    def __init__(self):
        self.reply = ""
        self.tokens = []
        self.calls = []

    async def generate(self, system_prompt, messages):
        self.calls.append(messages)
        return self.reply

    async def stream(self, system_prompt, messages):
        self.calls.append(messages)
        for token in self.tokens:
            yield token


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(agent, "_provider", llm)
    monkeypatch.setattr(agent, "_memory_provider", llm)
    return llm


class FakeConn:
    def __init__(self):
        self.conversation_exists = True
        self.executed = []

    async def fetchval(self, query, *args):
        return 1 if self.conversation_exists else None

    async def execute(self, query, *args):
        self.executed.append(query)


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


@pytest.fixture
def fake_db(monkeypatch):
    db = SimpleNamespace(conn=FakeConn(), saved=[], history=[], count=0, scheduled=[])

    async def add_message(conn, conversation_id, role, content):
        db.saved.append((role, content))

    async def fetch_messages(conn, conversation_id):
        return db.history

    async def create_conversation(conn):
        return uuid4()

    async def empty_list(*args):
        return []

    async def unconsolidated_count(conn, conversation_id):
        return db.count

    monkeypatch.setattr(main, "add_message", add_message)
    monkeypatch.setattr(main, "fetch_messages", fetch_messages)
    monkeypatch.setattr(main, "create_conversation", create_conversation)
    monkeypatch.setattr(main, "fetch_conversation_summary", empty_list)
    monkeypatch.setattr(main.memories, "list_memories_db", empty_list)
    monkeypatch.setattr(main, "get_unconsolidated_count", unconsolidated_count)
    monkeypatch.setattr(main, "schedule_consolidation", db.scheduled.append)
    monkeypatch.setattr(database, "pool", FakePool(db.conn))
    return db
