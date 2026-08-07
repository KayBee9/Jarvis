from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import pgvector.asyncpg

from app.config import get_settings
from app.models import Conversation, Message


class Database:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        settings = get_settings()
        if settings.database_url:
            self.pool = await asyncpg.create_pool(
                settings.database_url,
                init=pgvector.asyncpg.register_vector,
            )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    @property
    def is_configured(self) -> bool:
        return self.pool is not None


database = Database()


async def get_db() -> AsyncIterator[asyncpg.Connection | None]:
    """FastAPI dependency. Yields one connection per request, or None when DB is not configured."""
    if not database.pool:
        yield None
        return
    async with database.pool.acquire() as conn:
        yield conn


async def create_conversation(conn: asyncpg.Connection) -> UUID:
    row = await conn.fetchrow(
        """
        insert into conversations default values
        returning id
        """,
    )
    return row["id"]


async def get_previous_response_id(
    conn: asyncpg.Connection, conversation_id: UUID
) -> str | None:
    row = await conn.fetchrow(
        """
        select last_response_id
        from conversations
        where id = $1
        """,
        conversation_id,
    )
    return row["last_response_id"] if row else None


async def add_message(
    conn: asyncpg.Connection,
    conversation_id: UUID,
    role: str,
    content: str,
) -> None:
    async with conn.transaction():
        await conn.execute(
            """
            insert into messages (conversation_id, role, content)
            values ($1, $2, $3)
            """,
            conversation_id,
            role,
            content,
        )
        await conn.execute(
            """
            update conversations
            set updated_at = now()
            where id = $1
            """,
            conversation_id,
        )



async def fetch_conversation(
    conn: asyncpg.Connection, conversation_id: UUID
) -> Conversation | None:
    conversation = await conn.fetchrow(
        """
        select id, title, created_at, updated_at
        from conversations
        where id = $1
        """,
        conversation_id,
    )
    if not conversation:
        return None

    rows = await conn.fetch(
        """
        select id, conversation_id, role, content, created_at
        from messages
        where conversation_id = $1
        order by created_at asc
        """,
        conversation_id,
    )

    return Conversation(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation["updated_at"],
        messages=[Message(**dict(row)) for row in rows],
    )

async def fetch_messages(
    conn: asyncpg.Connection, conversation_id: UUID
) -> list[dict[str, str]]:
    """Return all messages for a conversation in chronological order,
       formatted for LLM Input"""
    rows = await conn.fetch(
        """
        select role, content
        from messages
        where conversation_id = $1
        order by created_at asc
        """,
        conversation_id,
    )
    return [{"role": row["role"], "content": row["content"]} for row in rows]

async def get_unconsolidated_count(
        conn: asyncpg.Connection, conversation_id: UUID 
) -> tuple[int, float]:
    """Return (count, oldest_age_minutes) of messages not yet consolidated for this conversation"""
    row = await conn.fetchrow(
        """
        with last_consolidated as (
            select m.created_at as ts
            from conversations c
            left join messages m on m.id = c.last_consolidated_message_id
            where c.id = $1
        )
        select count(*) as cnt
        from messages m, last_consolidated
        where m.conversation_id = $1
            and (last_consolidated.ts is null or m.created_at > last_consolidated.ts)
        """,
        conversation_id,
    )
    return int(row["cnt"])

async def fetch_unconsolidated_messages(
    conn: asyncpg.Connection, conversation_id: UUID
) -> list[dict]:
    """Return messages not yet consolidated for this conversation, oldest first."""
    rows = await conn.fetch(
        """
        with last_consolidated as (
            select m.created_at as ts
            from conversations c
            left join messages m on m.id = c.last_consolidated_message_id
            where c.id = $1
        )
        select m.id, m.role, m.content
        from messages m, last_consolidated
        where m.conversation_id = $1
          and (last_consolidated.ts is null or m.created_at > last_consolidated.ts)
        order by m.created_at asc
        """,
        conversation_id,
    )
    return [dict(row) for row in rows]


async def update_last_consolidated(
    conn: asyncpg.Connection, conversation_id: UUID, message_id: UUID
) -> None:
    """Update the last_consolidated_message_id for a conversation."""
    await conn.execute(
        """
        update conversations
        set last_consolidated_message_id = $2
        where id = $1
        """,
        conversation_id,
        message_id,
    )


async def fetch_conversation_summary(
    conn: asyncpg.Connection, current_conversation_id: UUID
) -> list[str] | None:
    """Return all summaries for a conversation EXCEPT the current one, newest first"""
    if current_conversation_id is None:
        # No current conversation, so return all summaries
        rows = await conn.fetch(
            """
            select summary
            from conversations
            where summary is not null
            order by updated_at desc
            """,
        )
    else:
        rows = await conn.fetch(
            """
            select summary
            from conversations
            where id != $1 and summary is not null
            order by updated_at desc
            """,
            current_conversation_id,
        )
    return [row["summary"] for row in rows]