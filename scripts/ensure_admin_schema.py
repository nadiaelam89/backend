"""Apply admin dashboard schema to the configured database (SQLite dev or PostgreSQL)."""
from __future__ import annotations

import asyncio

from app.db.models import Base
from app.db.session import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Admin dashboard tables ensured.")


if __name__ == "__main__":
    asyncio.run(main())
