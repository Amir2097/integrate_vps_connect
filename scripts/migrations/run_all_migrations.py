"""
Применяет все миграции к БД (добавляет недостающие колонки).
Запуск из корня проекта: python scripts/migrations/run_all_migrations.py
Использует DATABASE_URL из .env. После выполнения перезапустите бэкенд и бота.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text
from app.database import engine


MIGRATIONS = [
    ("users.is_blocked", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE"),
    ("payments.subscription_months", "ALTER TABLE payments ADD COLUMN IF NOT EXISTS subscription_months INTEGER NOT NULL DEFAULT 1"),
    ("vpn_clients.subscription_id", "ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS subscription_id INTEGER NULL REFERENCES subscriptions(id) ON DELETE SET NULL"),
    ("vpn_clients.is_blocked", "ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE"),
    ("subscriptions.display_name", "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NULL"),
    ("vpn_clients.display_name", "ALTER TABLE vpn_clients ADD COLUMN IF NOT EXISTS display_name VARCHAR(128) NULL"),
]


async def main():
    async with engine.begin() as conn:
        for name, sql in MIGRATIONS:
            try:
                await conn.execute(text(sql))
                print(f"  OK: {name}")
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"  -- {name}: уже есть")
                else:
                    print(f"  !! {name}: {e}")
        try:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_vpn_clients_subscription_id ON vpn_clients(subscription_id)"
            ))
            print("  OK: ix_vpn_clients_subscription_id")
        except Exception as e:
            if "already exists" not in str(e).lower():
                print(f"  !! index: {e}")
    print("Миграции применены. Перезапустите uvicorn и бота.")


if __name__ == "__main__":
    asyncio.run(main())
