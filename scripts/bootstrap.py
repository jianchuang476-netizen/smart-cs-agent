from __future__ import annotations

import asyncio

from app.db.seed import seed_database


async def main() -> None:
    result = await seed_database(ingest_documents=True)
    print("Bootstrap completed:", result)


if __name__ == "__main__":
    asyncio.run(main())
