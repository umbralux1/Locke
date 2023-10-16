from contextlib import suppress

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app import dp, db
from app.config import BANNER_VIDEO
from app.filters.channel_check import IsUserInNewsChannel
from app.filters.private_chat import IsPrivate
from app.filters.username import IsUserHasUsername
from app.handlers.settings_system.settings import find_best_matches_fuzzy_async
from app.keyboards.all_sites_menu import (
    get_better_pages_keyboard,
    make_place_pretty_view,
    Pagination,
    ShowSite,
)
from app.keyboards.cancel import cancel_button
from app.sites_config import sorted_sites, sites

router = Router()
dp.include_router(router)

flags = {"throttling_key": "default"}


@dp.message(
    F.text == "💼 Начать парсинг",
    IsPrivate(),
    IsUserHasUsername(),
    IsUserInNewsChannel(),
    flags=flags,
)
async def start_parser_handler(msg: types.Message, state: FSMContext):
    await state.set_state(None)

    user_state = await state.get_data()
    user_state["seller_item_sold_amount"] = ""
    user_state["item_rating_decline"] = ""
    user_state["item_has_delivery"] = ""
    user_state["item_views_amount"] = ""
    user_state["seller_gender"] = ""
    user_state["seller_item_bought_amount"] = ""
    user_state["seller_item_bought_amount"] = ""
    user_state["seller_join_date"] = ""
    user_state["item_insert_date"] = ""
    user_state["item_delivery_amount"] = ""
    await state.clear()
    await state.update_data(**user_state)
    # logger.debug()

    await db.add_user(user_id=msg.from_user.id, username=msg.from_user.username)
    await db.init_user_settings(user_id=msg.from_user.id)
    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        reply_markup=get_better_pages_keyboard(
            sorted_sites, repeat_last_parsing=1, search_place=1
        ),
        video=BANNER_VIDEO,
    )


@router.callback_query(Pagination.filter(F.show_key == "show_site"))
async def items_pagination(query: CallbackQuery, callback_data: Pagination):
    with suppress(ValueError, TelegramBadRequest):
        current_page = int(callback_data.page)

        await query.message.edit_reply_markup(
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                repeat_last_parsing=True,
                search_place=True,
                page=current_page,
            )
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(Pagination.filter(F.show_key == "search_place"))
async def search_place(
    query: CallbackQuery, callback_data: Pagination, state: FSMContext
):
    show_key = callback_data.page

    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption="""
🔎 Введите название площадки, которую хотите найти, либо укажите ее кодовое значение.

<b>Например: olx.kz, kz</b>""",
            reply_markup=cancel_button,
        )

    await state.set_state("search_place")
    await state.update_data(show_key=show_key)

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("search_place"))
async def search_place(msg: types.Message, state: FSMContext):
    search_place = msg.text.casefold()

    show_key = (await state.get_data()).get("show_key")
    # logger.debug(state)
    markup = InlineKeyboardBuilder()
    result = await find_best_matches_fuzzy_async(search_place, sites, top_n=3)
    # logger.debug(result)
    for place, _ in result:
        markup.button(
            text=make_place_pretty_view(place),
            callback_data=ShowSite(
                site=place,
                show_key=show_key,
            ).pack(),
        )
    markup.adjust(2)

    if not markup.as_markup().inline_keyboard:
        await msg.bot.send_video(
            chat_id=msg.from_user.id,
            reply_markup=cancel_button,
            video=BANNER_VIDEO,
            caption="По вашему запросу ничего не найдено.",
        )
        return

    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        reply_markup=markup.as_markup(),
        video=BANNER_VIDEO,
        caption=f"🔎 Результаты поиска по запросу: <b>{search_place}</b>",
    )

    await state.set_state(None)


@router.callback_query(Pagination.filter(F.show_key == "show_features"))
async def show_features(
    query: CallbackQuery, callback_data: Pagination, state: FSMContext
):
    feature_places = await db.get_user_features(user_id=query.from_user.id)
    if not feature_places:
        with suppress(TelegramAPIError):
            await query.answer("❌ У вас нет избранных площадок", show_alert=True)
            return

    show_key = callback_data.page
    feature_places = [record["site"] for record in feature_places]
    sorted_features = sorted(feature_places, key=lambda x: x.lower())

    markup = get_better_pages_keyboard(
        sorted_features, is_feature=False, page=1, show_key=show_key, search_place=True
    )
    with suppress(TelegramAPIError):
        await query.message.edit_caption(caption="", reply_markup=markup)

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(Pagination.filter(F.show_key == "back_to_first_page"))
async def back_to_first_page(query: CallbackQuery, callback_data: Pagination):
    show_key = callback_data.page
    repeat_last_parsing_val = show_key == "show_site"

    with suppress(TelegramAPIError):
        await query.message.edit_reply_markup(
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                search_place=True,
                repeat_last_parsing=repeat_last_parsing_val,
                show_key=show_key,
            )
        )

    with suppress(TelegramAPIError):
        await query.answer()
