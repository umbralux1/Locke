from typing import List

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from flag import flag

MAX_ITEMS_PER_PAGE = 18
FIRST_PAGE = 1
BLANK_SPACE = " "


def make_place_pretty_view(place: str) -> str:
    if not place:
        return place

    if place == "ebay.de":
        place = "EBAY-KLEINANZEIGEN.DE"

    site_code = place.split(".")[-1]
    if site_code == 'uk':
        site_code = 'gb'

    flag_emodji = flag(site_code.upper())

    return f"{flag_emodji} {place.upper()}"


def create_page_button(page: int, key: str, text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=Pagination(
            page=str(page),
            show_key=key,
        ).pack(),
    )


class ShowSite(CallbackData, prefix="show_site"):
    site: str
    show_key: str


class Pagination(CallbackData, prefix="pagination"):
    page: str
    show_key: str


def get_better_pages_keyboard(
    array: List,
    page: int = FIRST_PAGE,
    is_feature: int = True,
    repeat_last_parsing: int = False,
    search_place: int = False,
    show_key: str = "show_site",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    pagination_builder = InlineKeyboardBuilder()

    last_item_index = page * MAX_ITEMS_PER_PAGE
    sliced_array = array[(page - 1) * MAX_ITEMS_PER_PAGE : last_item_index]

    items_buttons = [
        InlineKeyboardButton(
            text=make_place_pretty_view(item),
            callback_data=ShowSite(site=item, show_key=show_key).pack(),
        )
        for item in sliced_array
    ]

    max_page = (len(array) + MAX_ITEMS_PER_PAGE - 1) // MAX_ITEMS_PER_PAGE

    previous_page = page - 1
    previous_page_text = "◀" if previous_page >= FIRST_PAGE else BLANK_SPACE
    previous_page = max(previous_page, 1)

    next_page = min(page + 1, max_page)
    next_page_text = "▶" if next_page <= max_page else BLANK_SPACE

    for button in items_buttons:
        builder.button(text=button.text, callback_data=button.callback_data)

    if is_feature:
        builder.button(
            text="⭐ Избранное",
            callback_data=Pagination(show_key="show_features", page=show_key).pack(),
        )
    if search_place:
        builder.button(
            text="🔍 Поиск",
            callback_data=Pagination(show_key="search_place", page=show_key).pack(),
        )
    if repeat_last_parsing:
        builder.button(
            text="🔍 Последний парсинг",
            callback_data="show_prst|last_parser|last_parser",
        )
    builder.adjust(2)

    pagination_builder.add(
        create_page_button(page=previous_page, key=show_key, text=previous_page_text),
        InlineKeyboardButton(
            text=f"{page}/{max_page}",
            callback_data=Pagination(
                show_key="back_to_first_page", page=show_key
            ).pack(),
        ),
        create_page_button(page=next_page, key=show_key, text=next_page_text),
    )

    main_markup = builder.as_markup()
    pagination_markup = pagination_builder.as_markup()
    main_markup.inline_keyboard += pagination_markup.inline_keyboard

    # logger.debug(main_markup)
    return main_markup
