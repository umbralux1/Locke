import ujson
from aiogram.types import ReplyKeyboardMarkup

from app.config import ADMINS


def get_start_menu_markup(user_id, json_output=False):
    markup_data = {
        "keyboard": [
            [{"text": "💼 Начать парсинг"}],
            [{"text": "⚙️ Настройки"}, {"text": "🤝 Реферальная программа"}],
            [{"text": "🆘 Помощь"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
        "input_field_placeholder": "Выберите действие",
    }

    if user_id in ADMINS:
        markup_data["keyboard"].insert(0, [{"text": "🔧 Админка"}])

    if json_output:
        return ujson.dumps(markup_data, ensure_ascii=False)

    return ReplyKeyboardMarkup(
        keyboard=markup_data["keyboard"],
        resize_keyboard=markup_data["resize_keyboard"],
        one_time_keyboard=markup_data["one_time_keyboard"],
        input_field_placeholder=markup_data["input_field_placeholder"],
    )
