from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.filters.admin import IsAdmin
from app.keyboards.all_sites_menu import (
    get_better_pages_keyboard,
    make_place_pretty_view,
    Pagination,
    ShowSite,
)
from app.sites_config import sorted_sites

router = Router()
dp.include_router(router)


@router.callback_query(F.data == "change_buy_site_status", IsAdmin())
async def change_buy_site_status(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="Выбери для какой площадки изменить статус",
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                page=1,
                is_feature=True,
                search_place=True,
                show_key="change_status_site",
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(Pagination.filter(F.show_key == "change_status_site"))
async def pagination_change_menu(query: CallbackQuery, callback_data: Pagination):
    with suppress(ValueError, TelegramAPIError):
        current_page = int(callback_data.page)
        await query.message.edit_reply_markup(
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                page=current_page,
                is_feature=True,
                search_place=True,
                show_key="change_status_site",
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


async def get_site_status_action(site):
    status = await db.get_site_status(site)
    if status == "activate":
        text = "Запретить взаимодейсвтие"
        callback = f"set_status_site|deactivate|{site}"
    else:
        text = "Разрешить взаимодейсвтие"
        callback = f"set_status_site|activate|{site}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=callback,
                )
            ]
        ]
    )


@router.callback_query(ShowSite.filter(F.show_key == "change_status_site"))
async def change_site(query: CallbackQuery, callback_data: ShowSite, state: FSMContext):
    site = callback_data.site

    await query.message.answer(
        f"Вы выбрали - {make_place_pretty_view(site)}\n\nВыберите действие",
        reply_markup=await get_site_status_action(site),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("set_status_site"))
async def set_status_site(query: CallbackQuery, state: FSMContext):
    new_status = query.data.split("|")[-2]
    site = query.data.split("|")[-1]

    await db.add_site_status(site, new_status)
    await query.message.edit_reply_markup(reply_markup=await get_site_status_action(site))

    await query.answer("Статус изменен!", show_alert=True)

    with suppress(TelegramAPIError):
        await query.answer()
