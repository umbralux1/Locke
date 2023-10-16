from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

ticket_operator_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✉️ Написать сообщение",
                callback_data="write_msg_ticket",
            )
        ],
        [
            InlineKeyboardButton(
                text="👤 Получить пользователя",
                callback_data="getuser_ticket",
            )
        ],
        [
            InlineKeyboardButton(
                text="📋 Детали заявки",
                callback_data="detail_ticket",
            )
        ],
        [
            InlineKeyboardButton(
                text="✅ Завершить обработку тикета",
                callback_data="close_ticket",
            )
        ],
    ]
)

ticket_user_menu = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="💬 Ответить", callback_data="user_write_msg_ticket"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Закрыть тикет",
                callback_data="close_ticket",
            )
        ],
    ]
)
