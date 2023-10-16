from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.all_sites_menu import ShowSite


def get_user_presets_buttons(site, user_presets):
    text_menu = InlineKeyboardBuilder()
    if user_presets:
        for text in user_presets:
            text_title = text.get("text_title")
            if text_title == "last_parser":
                continue

            text_menu.button(
                text=f"{text_title}", callback_data=f"show_prst|{site}|{text_title}"
            )
    else:
        text_menu.button(text="Пусто", callback_data="pass")

    text_menu.button(
        text="🗑 Удалить все пресеты", callback_data=f"delete_prsts_all|{site}"
    )

    text_menu.button(
        text="◀",
        callback_data=ShowSite(
            site=site,
            show_key="show_site",
        ).pack(),
    )

    text_menu.adjust(1)
    return text_menu.as_markup()


async def get_preset_actions(site, text_title, share_id, bot):
    share_preset_link = await create_start_link(payload=f"{share_id}PRESET", bot=bot)

    menu = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Стандартный",
                    callback_data=f"run_parser_preset|{site}|{text_title}",
                ),
                InlineKeyboardButton(
                    text="💤 Фоновый",
                    callback_data=f"run_parser_preset|{site}WATCH|{text_title}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Выставить текущий день (товара)",
                    callback_data=f'change_to_current_date|{site}|{text_title}',
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📎 Поделиться пресетом",
                    switch_inline_query=f"\n\n🔥 Советую тебе этот пресет {share_preset_link}",
                ),
            ],
        ]
    )

    if site != "last_parser":
        delete_btn = [
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"delete_prsts|{site}|{text_title}",
            )
        ]
        back_btn = [InlineKeyboardButton(text="◀", callback_data=f"presets|{site}")]

        menu.inline_keyboard.append(delete_btn)
        menu.inline_keyboard.append(back_btn)

    return menu
