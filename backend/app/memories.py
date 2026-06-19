import asyncpg
import pgvector.asyncpg
from uuid import UUID


async def create_memory_db(
    conn: asyncpg.Connection,
    content: str,
    embedding: list[float] | None,
) -> UUID:
    row = await conn.fetchrow(
        """
        insert into memories (content, embedding)
        values ($1, $2)
        returning id
        """,
        content,
        embedding,
    )
    return row["id"]


async def list_memories_db(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        select id, content, created_at
        from memories
        order by created_at desc
        """,
    )
    return [dict(row) for row in rows]


async def delete_memory_db(conn: asyncpg.Connection, memory_id: UUID) -> bool:
    result = await conn.execute(
        """
        delete from memories
        where id = $1
        """,
        memory_id,
    )
    return result.endswith(" 1")  # "DELETE 1" means one row was deleted


async def search_memories(
    conn: asyncpg.Connection,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.3,
) -> list[dict]:
    rows = await conn.fetch(
        """
        select id, content, created_at, 1 - (embedding <=> $1) as similarity
        from memories
        where embedding is not null and 1 - (embedding <=> $1) >= $2
        order by embedding <=> $1 asc
        limit $3
        """,
        query_embedding,
        min_similarity,
        top_k,
    )
    return [dict(row) for row in rows]