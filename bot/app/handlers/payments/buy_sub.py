import asyncio
import math
from contextlib import suppress

import aiohttp
import ujson
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiohttp_socks import ProxyConnector
from tenacity import retry, stop_after_attempt

from app import dp
from app.handlers.payments.anypay import anypay_create_invoice
from app.handlers.payments.payok import payok_create_invoice
from app.proxys import PROXY_FOR_CHECK_ALL

router = Router()
dp.include_router(router)


@retry(stop=stop_after_attempt(3), reraise=True)
async def get_curs_currency_rub(currency):
    currency = currency.upper()
    async with aiohttp.ClientSession(
        raise_for_status=True,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=9),
        connector=ProxyConnector.from_url(PROXY_FOR_CHECK_ALL, rdns=True),
    ) as cs:
        async with cs.get(
            "https://production.api.coindesk.com/v2/exchange-rates?assets=RUB",
            raise_for_status=True,
        ) as req:
            curs = await req.json(content_type=None)
            exchange_rate = curs.get("data").get("RUB").get("rate")
            exchange_rate = math.ceil(exchange_rate)

    async with aiohttp.ClientSession(
        raise_for_status=True,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=9),
        connector=ProxyConnector.from_url(PROXY_FOR_CHECK_ALL, rdns=True),
    ) as cs:
        async with cs.get(
            f"https://production.api.coindesk.com/v2/tb/price/ticker?assets={currency}",
        ) as req:
            curs = await req.json(content_type=None)
            curs = curs.get("data").get(currency).get("ohlc").get("c")
            return round(float(curs * exchange_rate), 2)


@router.callback_query(F.data.contains("buy_sub|"))
async def buy_sub(query: CallbackQuery):
    pay_method = query.data.split("|")[-3]
    site = query.data.split("|")[-2]
    time = query.data.split("|")[-1]

    if pay_method == "crypto_bot":
        with suppress(TelegramAPIError):
            await query.message.edit_caption(
                caption="▶️ Выберите в какой валюте хотите оплатить",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="BTC",
                                callback_data=f"crypto_bot_buy|btc|{site}|{time}",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text="ETH",
                                callback_data=f"crypto_bot_buy|eth|{site}|{time}",
                            ),
                            InlineKeyboardButton(
                                text="USDT",
                                callback_data=f"crypto_bot_buy|usdt|{site}|{time}",
                            ),
                        ],
                        [
                            InlineKeyboardButton(
                                text="USDC",
                                callback_data=f"crypto_bot_buy|usdc|{site}|{time}",
                            ),
                            InlineKeyboardButton(
                                text="BUSD",
                                callback_data=f"crypto_bot_buy|busd|{site}|{time}",
                            ),
                        ],
                    ]
                ),
            )
    elif pay_method == "any_pay":
        asyncio.create_task(
            anypay_create_invoice(
                query,
                site,
                time,
            )
        )
    elif pay_method == "payok":
        asyncio.create_task(
            payok_create_invoice(
                query,
                site,
                time,
            )
        )

    with suppress(TelegramAPIError):
        await query.answer()
