import asyncpg
import pgvector.asyncpg
from uuid import UUID

async def create_memory_db(conn: asyncpg.Connection, user_id: str, content: str,
                            embedding: list[float] | None) -> UUID:
    row = await conn.fetchrow(
        """
        insert into memories (user_id, content, embedding)
        values ($1, $2, $3)
        returning id
        """,
        user_id,
        content,
        embedding,
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

async def search_memories(
        conn: asyncpg.Connection,
        user_id: str,
        query_embedding: list[float],
        top_k: int = 5,
        min_similarity: float = 0.3,
) -> list[dict]:
    rows = await conn.fetch(
        """
        select id, content, created_at, 1 - (embedding <=> $1) as similarity
        from memories
        where user_id = $2 and embedding is not null and 1-(embedding <=> $1) >= $3
        order by embedding <=> $1 asc
        limit $4
        """,
        query_embedding,
        user_id,
        min_similarity,
        top_k,
    )
    return [dict(row) for row in rows]