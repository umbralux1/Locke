import asyncio
import traceback
from contextlib import suppress
from datetime import datetime, timedelta

import aiohttp
import ujson
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.deep_linking import create_start_link
from loguru import logger
from tenacity import stop_after_attempt, retry

from app import dp, db, bot
from app.config import CRYPTO_BOT_API, CHATS, BANNER_VIDEO
from app.handlers.payments.buy_sub import get_curs_currency_rub
from app.handlers.payments.cash_formatter import get_cash_by_day
from app.handlers.referral_system import add_time_to_referral
from app.handlers.site_actions import correct_days_form
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.quick_transition_to_site import get_place_access_btns
from app.misc.time_declension import humanize_date_v2
from app.misc.timezone_mapping import convert_to_user_timezone
from app.sites_config import sites

router = Router()
dp.include_router(router)


@retry(stop=stop_after_attempt(3), reraise=True)
async def create_crypto_bot_invoice(currency, price, query, site, time):
    curs_rub = await get_curs_currency_rub(currency)
    pay_value = round(float(price) / float(curs_rub), 8)
    pay_value = pay_value + (pay_value / 100 * 10)

    async with aiohttp.ClientSession(
        raise_for_status=True,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=9),
    ) as cs:
        async with cs.get(
            f"https://pay.crypt.bot/api/createInvoice?asset={currency}&amount={pay_value}&paid_btn_name=openBot&paid_btn_url={await create_start_link(payload=f'reply-{query.message.message_id}', bot=bot)}",
            headers={"Crypto-Pay-API-Token": CRYPTO_BOT_API},
        ) as req:
            res = await req.json(content_type=None)
            pay_url = res.get("result").get("pay_url")
            invoice_id = res.get("result").get("invoice_id")

    await db.add_payment_info(
        invoice_id, query.from_user.username, query.from_user.id, "unpaid"
    )

    with suppress(TelegramAPIError):
        pay_method_link = "<a href='https://t.me/CryptoBot'>🤖 CryptoBot</a>"

        await query.bot.send_message(
            text=f"""
{pay_method_link}
{query.from_user.mention_html()}
@{query.from_user.username}
{query.from_user.id}

— Время подписки: <b>{time} {correct_days_form(time)} </b>
— Площадка: <b>{make_place_pretty_view(site)}</b>
— Номер счета (для поиска): <b>{invoice_id}</b>

<b>Ссылка для оплаты:</b>
{pay_url}
        """,
            chat_id=CHATS.get("pay_logs"),
        )

        with suppress(TelegramBadRequest):
            await query.message.edit_caption(
                caption=f"""
{pay_method_link}

— Время подписки: <b>{time} {correct_days_form(time)} </b>
— Площадка: <b>{make_place_pretty_view(site)}</b>
— Номер счета (для поиска): <b>{invoice_id}</b>

<b>Ссылка для оплаты:</b>
{pay_url}
        """,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Проверить оплату",
                                callback_data=f"crypto_bot_check|{invoice_id}|{site}|{time}",
                            )
                        ],
                    ]
                ),
            )


@router.callback_query(F.data.contains("crypto_bot_buy|"))
async def crypto_bot_buy(query: CallbackQuery):
    currency = query.data.split("|")[-3]
    site = query.data.split("|")[-2]
    time = query.data.split("|")[-1]
    price = sites.get(site).get("price_by_day_amount").get(int(time))

    await query.message.edit_caption(caption="...")

    asyncio.create_task(create_crypto_bot_invoice(currency, price, query, site, time))

    with suppress(TelegramAPIError):
        await query.answer()


flags = {"throttling_key": "crypto_bot_check"}


@router.callback_query(F.data.contains("crypto_bot_check|"), flags=flags)
async def crypto_bot_check(query: CallbackQuery, state: FSMContext):
    try:
        invoice_id = query.data.split("|")[-3]
        site = query.data.split("|")[-2]
        time = query.data.split("|")[-1]

        async with aiohttp.ClientSession(
            raise_for_status=True,
            json_serialize=ujson.dumps,
            timeout=aiohttp.ClientTimeout(total=9),
        ) as cs:
            async with cs.get(
                f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}",
                headers={
                    "Crypto-Pay-API-Token": CRYPTO_BOT_API,
                },
            ) as req:
                res = await req.json(content_type=None)

        # logger.info(res)
        await query.bot.send_message(
            chat_id=CHATS.get("pay_logs"),
            text=f"""
▶️ Пользователь: <b>@{query.from_user.username}/ID-{query.from_user.id}</b>
▶️ Номер счета: <b>{invoice_id}</b>
▶️ Ответ сервера: <b>{res}</b>
                    """,
        )
        res = res.get("result").get("items")[0].get("status")
        if res != "paid":
            await query.message.answer("❌ Счет не оплачен")
            return

        status = await db.get_payment_status(query.from_user.id, invoice_id)
        if status == "paid":
            await query.message.answer("❌ Подписка уже выдана")
            return
        await db.update_payment_status(query.from_user.id, invoice_id, "paid")

        with suppress(Exception):
            await query.message.delete_reply_markup()

        new_expire_date = await db.add_subscription(
            site=site,
            new_expiry_date=datetime.now() + timedelta(days=int(time)),
            user_id=query.from_user.id,
        )

        await bot.send_video(
            chat_id=query.from_user.id,
            video=BANNER_VIDEO,
            caption=f"⏳ Подписка закончится: <b>{humanize_date_v2(await convert_to_user_timezone(new_expire_date, user_id=query.from_user.id))}</b>",
            reply_markup=get_place_access_btns(site),
        )

        await bot.send_message(
            chat_id=CHATS.get("logs"),
            text=f"""
#subscription

▶️ Купил: <b>{query.from_user.id} / @{query.from_user.username} </b>
▶️ Площадка: <b>{make_place_pretty_view(site)} </b>
▶️ Срок: <b>{time} дней </b>
▶️ Метод оплаты: <b>CryptoBot</b>
▶️ Транзакция: <b>{invoice_id}</b>
▶️ Дата окончания подписки: <b>{new_expire_date.strftime('%d.%m.%Y %H:%M')}</b>

{get_cash_by_day(int(time), site=site)}""",
        )

        await db.add_payment_stat(
            query.from_user.id,
            query.from_user.username,
            site,
            int(time),
        )
        await add_time_to_referral(query, int(time), query.from_user.id)

        await state.clear()
    except Exception:
        await query.message.answer("❌ Что-то пошло не так")
        logger.error(traceback.format_exc())
