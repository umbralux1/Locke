from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

cancel_button = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="❌ Отменить действие",
                callback_data="cancel_action",
            )
        ],
    ]
)

stop_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text="❌ Остановить парсинг",
            )
        ],
        [
            KeyboardButton(
                text="❌ Быстро остановить парсинг",
            )
        ],
        [
            KeyboardButton(
                text="❌ Остановить отправку сообщений",
            )
        ],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)
