import asyncpg
import pgvector.asyncpg
from uuid import UUID


async def create_memory_db(
    conn: asyncpg.Connection,
    content: str,
    embedding: list[float] | None,
) -> UUID:
    content = " ".join(content.split())
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
    top_k: int,
    min_similarity: float
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

async def update_memory_db(
        conn : asyncpg.Connection,
        memory_id: UUID,
        content: str,
        embedding: list[float] | None,
) -> bool:
    """Update a memory's content and embedding. Returns True if a row was updated."""
    content = " ".join(content.split())
    result = await conn.execute(
        """
        update memories
        set content = $1, embedding = $2
        where id = $3
        """,
        content,
        embedding,
        memory_id,
    )
    return result.endswith(" 1")

async def create_pending_change(
        conn: asyncpg.Connection,
        action: str,
        target_memory_id: UUID,
        target_content: str,
        proposed_content: str | None,
    ) -> UUID:
        """Save a REPLACE or DELETE pending the user's approval."""
        row = await conn.fetchrow(
             """
            insert into pending_memory_changes (action, target_memory_id, target_content, proposed_content)
            values ($1, $2, $3, $4)
            returning id
            """,
            action,
            target_memory_id,
            target_content,
            proposed_content,
        )  
        return row["id"]

async def list_pending_changes(conn: asyncpg.Connection) -> list[dict]:
    """Return all pending changes, newest first."""
    rows = await conn.fetch(
        """
        select id, action, target_memory_id, target_content, proposed_content, created_at
        from pending_memory_changes
        order by created_at desc
        """,
    )
    return [dict(row) for row in rows]

async def get_pending_change(
    conn: asyncpg.Connection, change_id: UUID
) -> dict | None:
    """Fetch a single pending change by id, or None if not found."""
    row = await conn.fetchrow(
        """
        select id, action, target_memory_id, target_content, proposed_content
        from pending_memory_changes
        where id = $1
        """,
        change_id,
    )
    return dict(row) if row else None

async def delete_pending_change(
    conn: asyncpg.Connection, change_id: UUID
) -> bool:
    """Remove a pending change. Used by both approve (after action runs) and skip."""
    result = await conn.execute(
        """
        delete from pending_memory_changes
        where id = $1
        """,
        change_id,
    )
    return result.endswith(" 1")