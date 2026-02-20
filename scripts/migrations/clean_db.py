"""
Очистка БД от тестовых данных: удаляет все платежи, VPN-клиенты, подписки и опционально пользователей.
Запуск из корня проекта (на сервере — так же, из каталога проекта с venv):
  python scripts/migrations/clean_db.py --yes              # только заявки/конфиги/подписки, пользователи остаются
  python scripts/migrations/clean_db.py --users --yes       # полная очистка, включая пользователей
Опции:
  --users   также удалить всех пользователей (полная очистка)
  --yes     не спрашивать подтверждение
Использует DATABASE_URL из .env (на сервере — из .env на сервере).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import text
from app.database import engine


async def main():
    import argparse
    p = argparse.ArgumentParser(description="Очистка БД от тестовых данных")
    p.add_argument("--users", action="store_true", help="Удалить также всех пользователей")
    p.add_argument("--yes", "-y", action="store_true", help="Не спрашивать подтверждение")
    args = p.parse_args()

    if not args.yes:
        scope = "платежи, VPN-клиенты, подписки" + (", пользователи" if args.users else "")
        ok = input(f"Удалить все данные: {scope}? (yes/no): ").strip().lower()
        if ok != "yes":
            print("Отменено.")
            return

    async with engine.begin() as conn:
        # Порядок: зависимости сначала (payments, vpn_clients), потом subscriptions, потом users
        await conn.execute(text("DELETE FROM payments"))
        print("  payments: удалено")
        await conn.execute(text("DELETE FROM vpn_clients"))
        print("  vpn_clients: удалено")
        await conn.execute(text("DELETE FROM subscriptions"))
        print("  subscriptions: удалено")
        if args.users:
            await conn.execute(text("DELETE FROM users"))
            print("  users: удалено")
    print("Готово. БД очищена.")


if __name__ == "__main__":
    asyncio.run(main())
