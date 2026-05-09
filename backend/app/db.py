from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from app.config import get_settings
from app.models import Conversation, Message


class Database:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        settings = get_settings()
        if settings.database_url:
            self.pool = await asyncpg.create_pool(settings.database_url)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[asyncpg.Connection]:
        if not self.pool:
            raise RuntimeError("DATABASE_URL is required for persistence")

        async with self.pool.acquire() as conn:
            yield conn

    @property
    def is_configured(self) -> bool:
        return self.pool is not None


database = Database()


async def create_conversation(user_id: str) -> UUID:
    async with database.connection() as conn:
        row = await conn.fetchrow(
            """
            insert into conversations (user_id)
            values ($1)
            returning id
            """,
            user_id,
        )
        return row["id"]


async def get_previous_response_id(conversation_id: UUID, user_id: str) -> str | None:
    async with database.connection() as conn:
        row = await conn.fetchrow(
            """
            select last_response_id
            from conversations
            where id = $1 and user_id = $2
            """,
            conversation_id,
            user_id,
        )
        return row["last_response_id"] if row else None


async def add_message(
    conversation_id: UUID,
    user_id: str,
    role: str,
    content: str,
    response_id: str | None = None,
) -> None:
    async with database.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                insert into messages (conversation_id, user_id, role, content)
                values ($1, $2, $3, $4)
                """,
                conversation_id,
                user_id,
                role,
                content,
            )
            if response_id:
                await conn.execute(
                    """
                    update conversations
                    set last_response_id = $1, updated_at = now()
                    where id = $2 and user_id = $3
                    """,
                    response_id,
                    conversation_id,
                    user_id,
                )
            else:
                await conn.execute(
                    """
                    update conversations
                    set updated_at = now()
                    where id = $1 and user_id = $2
                    """,
                    conversation_id,
                    user_id,
                )


async def fetch_conversation(conversation_id: UUID, user_id: str) -> Conversation | None:
    async with database.connection() as conn:
        conversation = await conn.fetchrow(
            """
            select id, title, created_at, updated_at
            from conversations
            where id = $1 and user_id = $2
            """,
            conversation_id,
            user_id,
        )
        if not conversation:
            return None

        rows = await conn.fetch(
            """
            select id, conversation_id, role, content, created_at
            from messages
            where conversation_id = $1 and user_id = $2
            order by created_at asc
            """,
            conversation_id,
            user_id,
        )

        return Conversation(
            id=conversation["id"],
            title=conversation["title"],
            created_at=conversation["created_at"],
            updated_at=conversation["updated_at"],
            messages=[Message(**dict(row)) for row in rows],
        )
