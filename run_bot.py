"""Запуск Telegram-бота (из корня проекта)."""
import asyncio
from bot.main import main

if __name__ == "__main__":
    asyncio.run(main())
