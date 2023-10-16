from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

token_buttons = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="⏮ Вставить свои токены из последнего запуска"),
        ],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)
