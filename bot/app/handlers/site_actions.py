from contextlib import suppress
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.keyboards.all_sites_menu import (
    get_better_pages_keyboard,
    make_place_pretty_view,
    ShowSite,
)
from app.keyboards.payments import get_payment_methods
from app.keyboards.site_actions import get_site_actions_btns
from app.misc.time_declension import humanize_date
from app.sites_config import sorted_sites, sites

router = Router()
dp.include_router(router)


def correct_days_form(days):
    days = int(days)

    if days % 10 == 1 and days % 100 != 11:
        return "день"
    elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
        return "дня"
    else:
        return "дней"


def gen_prices_btns(site):
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"Купить на {days} {correct_days_form(days)} [{price} RUB]",
                callback_data=f"choose_buy_method|{site}|{days}",
            )
        ]
        for days, price in sorted(
            sites.get(site).get("price_by_day_amount").items(), reverse=True
        )
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                text="🤝 Купить за реферальные дни",
                callback_data=f"buy_sub_ref|{site}",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def init_buy_sub_msg(site, query):
    special = sites.get(site).get("feature")
    special = f"\n▶ <b>Особенности площадки:</b> {special}\n" if special else ""

    filters = "\n".join([f"— {filter}" for filter in sites.get(site).get("filters")])

    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption=f"""{make_place_pretty_view(site)}
{special}
<b>▶ Фильтры площадки:</b>
{filters}
        """,
            reply_markup=gen_prices_btns(site),
        )


async def build_msg_text(query, site):
    expiry_date = await db.get_user_subscription_site(
        site=site, user_id=query.from_user.id
    )
    if not expiry_date or expiry_date and expiry_date < datetime.now():
        await init_buy_sub_msg(site, query)
        return

    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption=f"""
<b>🔎 Площадка:</b>
— <b>{make_place_pretty_view(site)}</b>

<b>⏳ Подписка закончится через: </b>
— {humanize_date(expiry_date, add_word=0)}
                """,
            reply_markup=get_site_actions_btns(
                is_feature=await db.get_user_features(user_id=query.from_user.id),
                site=site,
            ),
        )


@router.callback_query(ShowSite.filter(F.show_key == "show_site"))
async def show_site(query: CallbackQuery, callback_data: ShowSite):
    site = callback_data.site

    status = await db.get_site_status(site)
    if status != "activate" and status is not None:
        await query.answer("Данная площадка временно отключена!", show_alert=True)
        return

    await build_msg_text(query, site)

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("choose_buy_method|"))
async def choose_buy_method(query: CallbackQuery):
    site = query.data.split("|")[-2]
    time = query.data.split("|")[-1]

    if sites.get(site).get("feature"):
        await query.answer(sites.get(site).get("feature"), show_alert=True)

    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption="▶️ Выберите метод оплаты",
            reply_markup=get_payment_methods(
                site=site,
                time=time,
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(query: CallbackQuery):
    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption="",
            reply_markup=get_better_pages_keyboard(
                sorted_sites, repeat_last_parsing=1, search_place=1
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("renew_subscription"))
async def renew_subscription(query: CallbackQuery):
    site = query.data.split("|")[-1]

    await init_buy_sub_msg(site, query)

    with suppress(TelegramAPIError):
        await query.answer()
