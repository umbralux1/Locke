from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.all_sites_menu import ShowSite


def get_user_custom_text_buttons(
    site, user_text, sender_select=False, show_callback=""
):
    if not sender_select:
        show_callback = "show_ct"

    text_menu = InlineKeyboardBuilder()
    if user_text:
        for text in user_text:
            text_title = text.get("text_title")

            text_menu.button(
                text=f"💬 {text_title}",
                callback_data=f"{show_callback}|{text_title}|{site}",
            )
    else:
        text_menu.button(
            text="Пусто",
            callback_data="pass",
        )

    text_menu.button(
        text="➕ Добавить новый текст",
        callback_data=f"add_ct|{site}",
    )

    if not sender_select:
        text_menu.button(
            text="🗑 Удалить все текста",
            callback_data=f"delete_all_ct|{site}",
        )

        text_menu.button(
            text="◀",
            callback_data=ShowSite(
                site=site,
                show_key="show_site",
            ).pack(),
        )

    if sender_select:
        text_menu.button(
            text="Рандомный выбор каждый раз",
            callback_data=f"{show_callback}|any|{site}",
        )

    text_menu.adjust(1)
    return text_menu.as_markup()


def get_item_custom_msg_actions(site, text_title, text_body):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Редактировать",
                    callback_data=f"edit_text_custom|{site}|{text_title}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить",
                    callback_data=f"delete_current_ct|{site}|{text_title}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📎 Поделиться кастомным текстом",
                    switch_inline_query=f"\n\n🔥 Советую тебе этот кастомный текст\n\nНазвание: {text_title}\nТекст: {text_body}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="◀",
                    callback_data=f"custom_text|{site}",
                ),
            ],
        ]
    )
