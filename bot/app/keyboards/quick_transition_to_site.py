from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.keyboards.all_sites_menu import ShowSite


def get_place_access_btns(site):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Перейти к площадке",
                    callback_data=ShowSite(
                        site=site,
                        show_key="show_site",
                    ).pack()
                ),
            ],
        ]
    )
