from contextlib import suppress
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app import dp, db, bot
from app.config import CHATS, BANNER_VIDEO
from app.handlers.payments.cash_formatter import get_cash_by_day
from app.handlers.referral_system import add_time_to_referral
from app.keyboards.all_sites_menu import (
    get_better_pages_keyboard,
    make_place_pretty_view,
    Pagination,
    ShowSite,
)
from app.keyboards.cancel import cancel_button
from app.keyboards.quick_transition_to_site import get_place_access_btns
from app.misc.time_declension import humanize_date_v2
from app.misc.timezone_mapping import convert_to_user_timezone
from app.sites_config import sorted_sites

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("admin_subscription"))
async def admin_subscription(query: CallbackQuery, state: FSMContext):
    action = query.data.split("|")[-1]
    user_id = query.data.split("|")[-2]

    with suppress(TelegramBadRequest):
        if action == "give":
            await query.message.edit_caption(
                caption="Выбери какую площадку выдать",
                reply_markup=get_better_pages_keyboard(
                    sorted_sites,
                    page=1,
                    is_feature=True,
                    search_place=True,
                    show_key="admin_give_sub",
                ),
            )
        else:
            await query.message.edit_caption(
                caption="Выбери с какой площадки забрать",
                reply_markup=get_better_pages_keyboard(
                    sorted_sites,
                    page=1,
                    is_feature=True,
                    search_place=True,
                    show_key="admin_give_take",
                ),
            )

    await state.update_data(user_id=user_id)

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(Pagination.filter(F.show_key == "admin_give_sub"))
async def pagination_change_menu(query: CallbackQuery, callback_data: Pagination):
    with suppress(ValueError, TelegramAPIError):
        current_page = int(callback_data.page)
        await query.message.edit_reply_markup(
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                page=current_page,
                is_feature=True,
                search_place=True,
                show_key="admin_give_sub",
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(Pagination.filter(F.show_key == "admin_give_take"))
async def pagination_change_menu(query: CallbackQuery, callback_data: Pagination):
    with suppress(ValueError, TelegramAPIError):
        current_page = int(callback_data.page)
        await query.message.edit_reply_markup(
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                page=current_page,
                is_feature=True,
                search_place=True,
                show_key="admin_give_take",
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(ShowSite.filter(F.show_key == "admin_give_sub"))
async def admin_give_sub(
    query: CallbackQuery, callback_data: ShowSite, state: FSMContext
):
    site = callback_data.site

    await query.message.answer(
        f"Вы выбрали - {make_place_pretty_view(site)}\n\nСколько часов выдать?",
        reply_markup=cancel_button,
    )

    await state.update_data(site=site)
    await state.set_state("get_admin_sub_give_hours")

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(ShowSite.filter(F.show_key == "admin_give_take"))
async def admin_give_take(query: CallbackQuery, callback_data: ShowSite, state: FSMContext):
    site = callback_data.site

    user_data = await state.get_data()
    user_id = user_data.get("user_id")
    await state.update_data(site=site)

    await query.message.answer(
        f"""
▶️ Пользователь: ID-{user_id}
▶️ Площадка: {make_place_pretty_view(site)}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Забрать",
                        callback_data="confirm_admin_sub|take",
                    )
                ],
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("get_admin_sub_give_hours"))
async def get_admin_sub_give_hours(msg: Message, state: FSMContext):
    hours = msg.text

    if not hours.isdigit():
        await msg.answer("❌ Введи число")
        return

    user_data = await state.get_data()
    user_id = user_data.get("user_id")
    site = user_data.get("site")

    await state.update_data(hours=hours)
    await msg.answer(
        f"""
▶️ Пользователь: ID-{user_id}
▶️ Площадка: {make_place_pretty_view(site)}
▶️ Часов добавится: {hours}""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Начислить",
                        callback_data="confirm_admin_sub|give",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.contains("confirm_admin_sub"))
async def confirm_admin_sub(query: CallbackQuery, state: FSMContext):
    action = query.data.split("|")[-1]
    user_data = await state.get_data()
    user_id = user_data.get("user_id")
    site = user_data.get("site")
    hours = user_data.get("hours")

    if action == "give":
        new_expire_date = await db.add_subscription(
            site=site,
            new_expiry_date=datetime.now() + timedelta(hours=int(hours)),
            user_id=int(user_id),
        )

        await bot.send_video(
            chat_id=user_id,
            video=BANNER_VIDEO,
            caption=f"⏳ Подписка закончится: <b>{humanize_date_v2(await convert_to_user_timezone(new_expire_date, user_id=int(user_id)))}</b>",
            reply_markup=get_place_access_btns(site),
        )

        row_id = await db.add_payment_stat(
            query.from_user.id,
            query.from_user.username,
            site,
            int(hours),
        )

        await bot.send_message(
            chat_id=CHATS.get("logs"),
            text=f"""
#admin_sub

▶️ Админ: <b>{query.from_user.mention_html()}</b>
▶️ Выдал: <b>ID-{user_id}</b>
▶️ Срок: <b>{hours} часов </b>
▶️ Площадка: <b>{make_place_pretty_view(site)}</b>

{get_cash_by_day(hours, site=site)}
                    """,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Не учитывать в кассу",
                            callback_data=f"payment_decline|{row_id}",
                        )
                    ],
                ]
            ),
        )
        await add_time_to_referral(query, hours, user_id)
        await query.message.edit_text("✅️️️️️️️ Выдано")
    else:
        await db.remove_subscription(user_id=int(user_id), site=site)
        await bot.send_message(
            chat_id=CHATS.get("logs"),
            text=f"""
#admin_sub

▶️ Админ: <b>{query.from_user.mention_html()}</b>
▶️ Забрал: <b>ID-{user_id}</b>
▶️ Площадка: <b>{make_place_pretty_view(site)}</b>""",
        )

        await query.message.edit_text("✅️️️️️️️ Успешно убрано")

    with suppress(TelegramAPIError):
        await query.answer()

    await state.clear()


@router.callback_query(F.data.contains("payment_decline"))
async def payment_decline(query: CallbackQuery):
    row_id = query.data.split("|")[-1]
    if row_id == "None":
        await query.answer("❌ Платеж не найден", show_alert=True)
        return

    await query.message.edit_text(f"{query.message.text}\n\n❌ Не учитывается в кассе")
    await db.delete_payment(row_id=int(row_id))

    with suppress(TelegramAPIError):
        await query.answer()
