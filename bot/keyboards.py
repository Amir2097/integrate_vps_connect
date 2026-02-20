from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔗 Подключиться"),
                KeyboardButton(text="✅ Я оплатил(а)"),
            ],
            [
                KeyboardButton(text="📋 Мои подписки"),
                KeyboardButton(text="📖 Инструкции"),
            ],
        ],
        resize_keyboard=True,
    )
