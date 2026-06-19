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
    response_id: str | None = None,
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
        if response_id:
            await conn.execute(
                """
                update conversations
                set last_response_id = $1, updated_at = now()
                where id = $2
                """,
                response_id,
                conversation_id,
            )
        else:
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