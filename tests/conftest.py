from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_smart_cs.db")
os.environ.setdefault("CHECKPOINT_BACKEND", "memory")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-with-enough-length")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")
os.environ.setdefault("AUTO_SEED", "true")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399/15")

import pytest

from app.db.session import dispose_db


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database():
    yield
    asyncio.run(dispose_db())
    time.sleep(0.2)
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"data/test_smart_cs.db{suffix}")
        if path.exists():
            path.unlink()
