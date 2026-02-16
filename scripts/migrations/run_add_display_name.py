"""
Добавляет колонки display_name в subscriptions и vpn_clients.
Запуск из корня проекта: python scripts/migrations/run_add_display_name.py
Использует DATABASE_URL из .env (через app.config).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text
from app.database import engine


async def main():
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NULL"
        ))
    print("Колонки display_name добавлены (или уже существуют).")


if __name__ == "__main__":
    asyncio.run(main())
