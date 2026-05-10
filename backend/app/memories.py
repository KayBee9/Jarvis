import asyncpg
from uuid import UUID

async def create_memory_db(conn: asyncpg.Connection, user_id: str, content: str) -> UUID:
    row = await conn.fetchrow(
        """
        insert into memories (user_id, content)
        values ($1, $2)
        returning id
        """,
        user_id,
        content,
    )
    return row["id"]

async def list_memories_db(conn: asyncpg.Connection, user_id: str) -> list[dict]:
    rows = await conn.fetch(
        """
        select id, content, created_at
        from memories
        where user_id = $1
        order by created_at desc
        """,
        user_id,
    )
    return [dict(row) for row in rows]

async def delete_memory_db(conn: asyncpg.Connection, user_id: str, memory_id: UUID) -> bool:
    result = await conn.execute(
        """
        delete from memories
        where id = $1 and user_id = $2
        """,
        memory_id,
        user_id,
    )
    return result.endswith(" 1")  # "DELETE 1" means one row was deleted
