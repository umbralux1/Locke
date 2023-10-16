import hashlib
import random
import traceback
from contextlib import suppress
from datetime import datetime, timedelta

import aiohttp
import ujson
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.deep_linking import create_start_link
from aiohttp_socks import ProxyConnector
from loguru import logger
from tenacity import retry, stop_after_attempt

from app import db, dp, bot
from app.config import (
    CHATS,
    PAYOK_API,
    PAYOK_SHOP_ID,
    PAYOK_LC_API,
    PAYOK_LC_API_ID,
    BANNER_VIDEO,
)
from app.handlers.payments.cash_formatter import get_cash_by_day
from app.handlers.referral_system import add_time_to_referral
from app.handlers.site_actions import correct_days_form
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.quick_transition_to_site import get_place_access_btns
from app.misc.time_declension import humanize_date_v2
from app.misc.timezone_mapping import convert_to_user_timezone
from app.proxys import PROXY_FOR_CHECK_ALL
from app.sites_config import sites

router = Router()
dp.include_router(router)


@retry(stop=stop_after_attempt(3), reraise=True)
async def check_payment_payok(proxy, data, bot, payment_id, query):
    def get_transaction_status(data):
        for key, value in data.items():
            if key.isdigit():
                transaction_status = value.get("transaction_status")
                if transaction_status == "1":
                    return transaction_status
        return data

    async with aiohttp.ClientSession(
        raise_for_status=True,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=9),
        connector=ProxyConnector.from_url(proxy, rdns=False),
    ) as cs:
        async with cs.post("https://payok.io/api/transaction", data=data) as req:
            response = await req.json(content_type=None)

    user_info = f"@{query.from_user.username}/ID-{query.from_user.id}"
    await bot.send_message(
        chat_id=CHATS.get("pay_logs"),
        text=f"""
▶️ Пользователь: <b>{user_info}</b>
▶️ Номер счета: <b>{payment_id}</b>
▶️ Ответ сервера: <b>{response}</b>
        """,
    )

    return response.get("error_text") or get_transaction_status(response)


flags = {"throttling_key": "payok_check"}


@router.callback_query(F.data.contains("payok_check|"), flags=flags)
async def payok_check(query: CallbackQuery):
    payment_id = query.data.split("|")[-3]
    site = query.data.split("|")[-2]
    time = query.data.split("|")[-1]

    data = {
        "API_ID": PAYOK_LC_API_ID,
        "API_KEY": PAYOK_LC_API,
        "shop": PAYOK_SHOP_ID,
        "payment": int(payment_id),
    }

    try:
        response = await check_payment_payok(
            PROXY_FOR_CHECK_ALL, data, query.bot, payment_id, query
        )
        if "не найден" in response:
            await query.message.answer(
                "❌ Транзакция не найдена\n\n<a href='https://telegra.ph/1'>Подробнее</a>"
            )
            return
        if response != "1":
            await query.message.answer(
                "❌ Оплата не прошла\n\n<a href='https://telegra.ph/1'>Подробнее</a>"
            )
            return
    except Exception:
        logger.error(traceback.format_exc())
        await query.message.answer(
            "❌ Сервер оплаты недоступен, попробуйте позже\n\n<a href='https://telegra.ph/1'>Подробнее</a>"
        )
        return

    status = await db.get_payment_status(query.from_user.id, payment_id)
    if status == "paid":
        await query.message.answer("❌ Подписка уже выдана")
        return
    await db.update_payment_status(query.from_user.id, payment_id, "paid")

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
▶️ Срок: <b>{time} {correct_days_form(time)} </b>
▶️ Метод оплаты: <b>PAYOK</b>
▶️ Транзакция: <b>{payment_id}</b>
▶️ Дата окончания подписки: <b>{new_expire_date.strftime('%d.%m.%Y %H:%M')}</b>

{get_cash_by_day(time, site=site)}
        """,
    )
    await db.add_payment_stat(
        query.from_user.id,
        query.from_user.username,
        site,
        int(time),
    )

    await add_time_to_referral(query, time, query.from_user.id)

    with suppress(TelegramAPIError):
        await query.answer()


async def payok_create_invoice(query: CallbackQuery, site, time):
    payment = str(random.randint(0, 999_999_999))
    currency = "RUB"
    amount = sites.get(site).get("price_by_day_amount").get(int(time))
    amount = str(((float(amount) / 100) * 7.5) + float(amount))
    description = "Подписка"

    sign = "|".join(
        [
            amount,
            payment,
            PAYOK_SHOP_ID,
            currency,
            description,
            PAYOK_API,
        ]
    )

    link_to_msg = await create_start_link(
        payload=f"reply-{query.message.message_id}", bot=bot
    )

    sign = hashlib.md5(sign.encode()).hexdigest()
    payment_url = f"https://payok.io/pay?amount={amount}&payment={payment}&shop={PAYOK_SHOP_ID}&desc={description}&success_url={link_to_msg}&sign={sign}"
    await db.add_payment_info(
        payment, query.from_user.username, query.from_user.id, "unpaid"
    )

    await query.bot.send_message(
        text=f"""
#PAYOK
{query.from_user.mention_html()}
@{query.from_user.username}
{query.from_user.id}

— Время подписки: <b>{time} {correct_days_form(time)} </b>
— Площадка: <b>{make_place_pretty_view(site)}</b>
— Номер счета (для поиска): <b>{payment}</b>
        """,
        chat_id=CHATS.get("pay_logs"),
    )

    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption=f"""
— Время подписки: <b>{time} {correct_days_form(time)}</b>
— Площадка: <b>{make_place_pretty_view(site)}</b>
— Номер счета (для поиска): <b>{payment}</b>

💡 <b>Если вы будете оплачивать через эту ссылку, оплата пройдет только через кнопку, которая ниже, если вы пересоздадите оплату и нажмете другую кнопку проверить оплату, оплата не выдастся! Лучше закрепите это сообщение, чтобы его не потерять. Не удаляйте это сообщение и не очищайте переписку с ботом иначе ваша оплата утеряется</b>
""",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Перейти к оплате", url=payment_url)],
                    [
                        InlineKeyboardButton(
                            text="Проверить оплату",
                            callback_data=f"payok_check|{payment}|{site}|{time}",
                        ),
                    ],
                ]
            ),
        )
