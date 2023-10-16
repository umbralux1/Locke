from datetime import datetime, timedelta
from time import perf_counter
from typing import List

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from loguru import logger

from app import db


async def generate_keyboard(
    defaults: List[str], saved_value: str, additional_buttons=None, row_width=3
):
    if additional_buttons is None:
        additional_buttons = []

    if saved_value and saved_value not in defaults:
        saved_value += " ⭐"
        defaults.insert(0, saved_value)

    keyboard = [defaults[i : i + row_width] for i in range(0, len(defaults), row_width)]
    keyboard = [[KeyboardButton(text=val) for val in sublist] for sublist in keyboard]

    keyboard.extend([KeyboardButton(text=btn)] for btn in additional_buttons)
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        row_width=row_width,
        one_time_keyboard=False,
    )


async def get_seller_item_amount(save_type, user_id, site):
    # t1_start = perf_counter()
    keyword = await db.get_user_saved_keyword(user_id, site, save_type) or "5"
    # logger.debug(f"db get_user_saved_keyword save_type: {perf_counter() - t1_start}")

    default_buttons = ["5", "10", "Не использовать фильтр", "❌ Отмена"]

    if keyword in default_buttons:
        default_buttons.remove(keyword)

    keyword += " ⭐"
    buttons = [keyword] + default_buttons

    return await generate_keyboard(buttons, keyword, row_width=2)


async def get_price_parser_btns(save_type, user_id, site):
    # t1_start = perf_counter()
    keyword = await db.get_user_saved_keyword(user_id, site, save_type) or "1-9999999"
    # logger.debug(f"db get_user_saved_keyword: {perf_counter() - t1_start}")
    default_buttons = ["1-9999999", "Не использовать фильтр", "❌ Отмена"]
    if keyword in default_buttons:
        default_buttons.remove(keyword)

    keyword += " ⭐"
    buttons = [keyword] + default_buttons

    return await generate_keyboard(buttons, keyword, row_width=2)


async def get_seller_date_button(save_type, user_id, site):
    keyword = (
        await db.get_user_saved_keyword(user_id, site, save_type)
        or f"01-01-{int(datetime.now().year)}"
    )
    default_buttons = [
        f"01-01-{int(datetime.now().year)}",
        "Не использовать фильтр",
        "❌ Отмена",
    ]
    if keyword in default_buttons:
        default_buttons.remove(keyword)

    keyword += " ⭐"
    buttons = [keyword] + default_buttons

    return await generate_keyboard(buttons, keyword, row_width=2)


async def get_ads_date_button(save_type, user_id, site):
    keyword = await db.get_user_saved_keyword(user_id, site, save_type) or (
        datetime.now() - timedelta(days=4)
    ).strftime("%d-%m-%Y")
    default_buttons = [
        str(datetime.now().strftime("%d-%m-%Y")),
        (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y"),
        (datetime.now() - timedelta(days=2)).strftime("%d-%m-%Y"),
        (datetime.now() - timedelta(days=3)).strftime("%d-%m-%Y"),
        "Не использовать фильтр",
        "❌ Отмена",
    ]
    if keyword in default_buttons:
        default_buttons.remove(keyword)

    keyword += " ⭐"
    buttons = [keyword] + default_buttons

    return await generate_keyboard(buttons, keyword, row_width=2)


async def get_views_amount_btns(save_type, user_id, site):
    keyword = await db.get_user_saved_keyword(user_id, site, save_type) or "500"
    default_buttons = [
        "1000",
        "2000",
        "4000",
        "Не использовать фильтр",
        "❌ Отмена",
    ]
    if keyword in default_buttons:
        default_buttons.remove(keyword)

    keyword += " ⭐"
    buttons = [keyword] + default_buttons

    return await generate_keyboard(buttons, keyword, row_width=2)


async def get_success_delivery_amount_btns(save_type, user_id, site):
    keyword = await db.get_user_saved_keyword(user_id, site, save_type) or "0"
    default_buttons = [
        "0",
        "5",
        "10",
        "Не использовать фильтр",
        "❌ Отмена",
    ]
    if keyword in default_buttons:
        default_buttons.remove(keyword)

    keyword += " ⭐"
    buttons = [keyword] + default_buttons

    return await generate_keyboard(buttons, keyword, row_width=2)


choice_btns = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Да"),
        ],
        [
            KeyboardButton(text="Нет"),
        ],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    row_width=2,
    one_time_keyboard=False,
)

delivery_choice_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Только с доставкой"),
        ],
        [
            KeyboardButton(text="Только без доставки"),
        ],
        [
            KeyboardButton(text="Не использовать фильтр"),
        ],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    row_width=2,
    one_time_keyboard=False,
)

gender_select_button = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Мужской"),
            KeyboardButton(text="Женский"),
        ],
        [KeyboardButton(text="Не использовать фильтр")],
        [KeyboardButton(text="❌ Отмена")],
    ],
    resize_keyboard=True,
    row_width=2,
    one_time_keyboard=False,
)
