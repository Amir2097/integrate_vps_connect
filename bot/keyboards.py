from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔗 Подключиться"),
                KeyboardButton(text="✅ Я оплатил(а)"),
                KeyboardButton(text="📋 Моя подписка"),
            ],
            [
                KeyboardButton(text="📥 Получить конфиг"),
                KeyboardButton(text="💳 Реквизиты для оплаты"),
                KeyboardButton(text="📖 Инструкция по установке"),
            ],
        ],
        resize_keyboard=True,
    )
