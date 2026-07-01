"""Clear all orders and events from local/dev database."""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import engine


async def main() -> None:
    statements = [
        "DELETE FROM analytics_events",
        "DELETE FROM order_items",
        "DELETE FROM site_events",
        "DELETE FROM orders",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                result = await conn.execute(text(stmt))
                print(f"{stmt} -> {result.rowcount} rows")
            except Exception as exc:
                print(f"{stmt} -> skipped ({exc})")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
