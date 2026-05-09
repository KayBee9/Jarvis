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
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            print(f"Running {migration.name}...")
            sql = migration.read_text(encoding="utf-8")
            await conn.execute(sql)
            print(f"Done: {migration.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
