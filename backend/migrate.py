import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent / "supabase" / "migrations"


async def run_migrations() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in .env")

    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(
            """
            do $$
            begin
                if not exists (
                    select 1 from pg_tables
                    where schemaname = 'public' and tablename = '_schema_migrations'
                ) then
                    create table _schema_migrations (
                        filename text primary key,
                        applied_at timestamptz not null default now()
                    );
                    alter table _schema_migrations enable row level security;
                end if;
            end$$;
            """
        )
        applied = {
            row["filename"]
            for row in await conn.fetch("select filename from _schema_migrations")
        }
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name in applied:
                print(f"Skipping {migration.name} (already applied)")
                continue
            print(f"Running {migration.name}...")
            sql = migration.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "insert into _schema_migrations (filename) values ($1)",
                    migration.name,
                )
            print(f"Done: {migration.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
