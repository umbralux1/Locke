from collections import Counter
from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.filters.admin import IsAdmin
from app.handlers.payments.cash_formatter import get_cash_by_day
from app.keyboards.all_sites_menu import make_place_pretty_view

router = Router()
dp.include_router(router)


@router.callback_query(F.data == "get_cash_report", IsAdmin())
async def get_cash_report(query: CallbackQuery, state: FSMContext):
    await query.message.answer(
        "Выбери период",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="За день",
                        callback_data="get_csh_rep|day",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="За месяц",
                        callback_data="get_csh_rep|month",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="За год",
                        callback_data="get_csh_rep|year",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="Свой вариант",
                        callback_data="get_csh_rep|custom",
                    )
                ],
            ]
        ),
    )


async def count_payments(payments, push_text):
    places_top = []
    percent_cash_summary = 0
    for count, payment in enumerate(payments, start=1):
        with suppress(Exception):
            place = payment.get("place")
            places_top.append(place)
            days_amount = payment.get("days_amount")
            cash_text = get_cash_by_day(int(days_amount), place)

            percent_cash_summary += float(
                cash_text.replace("💰 ~", "").replace("р.", "")
            )

    push_text += f"💰 Выручка за день ~{round(percent_cash_summary, 2)}\n\n"
    places_top = Counter(places_top)
    places_top = dict(
        sorted(places_top.items(), key=lambda x: float(x[1]), reverse=True)
    )

    for key, value in places_top.items():
        push_text += "{0} купили {1} раз\n".format(
            f"{make_place_pretty_view(key)}",
            value,
        )

    return push_text


async def send_payment_text(msg, top_text, payments):
    if not payments:
        await msg.answer("Пока нету продаж :c")
        return

    push_text = await count_payments(payments, top_text)

    if len(push_text) > 4096:
        for x in range(0, len(push_text), 4096):
            await msg.answer(push_text[x : x + 4096])
    else:
        await msg.answer(push_text)


@router.callback_query(F.data.contains("get_csh_rep"))
async def get_csh_rep(query: CallbackQuery, state: FSMContext):
    period = query.data.split("|")[-1]
    if period == "custom":
        await query.message.answer("Введите кол-во дней")
        await state.set_state("get_csh_rep_custom")
        return

    if period == "day":
        payments = await db.get_payments(days=1)
    else:
        payments = await db.get_payments_by_word(word=period)

    await send_payment_text(
        query.message,
        f"💼 Продажи за {period.replace('month', 'месяц').replace('year', 'год').replace('day', 'день')}:\n\n",
        payments,
    )


@router.message(Command("getday"), IsAdmin())
async def get_day(msg):
    payments = await db.get_payments(days=1)

    await send_payment_text(
        msg,
        f"💼 Продажи за день:\n\n",
        payments,
    )


@router.message(Command("getmonth"), IsAdmin())
async def get_month(msg):
    payments = await db.get_payments_by_word(word="month")

    await send_payment_text(
        msg,
        f"💼 Продажи за месяц:\n\n",
        payments,
    )


@router.message(StateFilter("get_csh_rep_custom"), IsAdmin())
async def get_csh_rep_custom(msg, state: FSMContext):
    days = msg.text
    if not days.isdigit():
        await msg.answer("Введите число")
        return

    payments = await db.get_payments(days=int(days))
    await send_payment_text(
        msg,
        f"💼 Продажи за {days} дней:\n\n",
        payments,
    )

    await state.clear()
