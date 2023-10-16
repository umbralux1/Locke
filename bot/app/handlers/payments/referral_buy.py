from contextlib import suppress
from datetime import datetime, timedelta

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.config import CHATS, BANNER_VIDEO
from app.handlers.site_actions import correct_days_form
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.cancel import cancel_button
from app.keyboards.quick_transition_to_site import get_place_access_btns
from app.misc.time_declension import humanize_date_v2
from app.misc.timezone_mapping import convert_to_user_timezone
from app.sites_config import sites

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("buy_sub_ref"))
async def buy_sub_ref(query: CallbackQuery, state: FSMContext):
    site = query.data.split("|")[-1]

    with suppress(TelegramAPIError):
        await query.answer()

    day_referral = await db.get_user_referral_days(user_id=query.from_user.id)
    if day_referral is None:
        await query.message.answer("❌ Пропишите /start и повторите действие")
        return

    if day_referral <= 0:
        await query.message.answer(
            "❌ У вас нет бонусных дней, чтобы узнать подробнее нажми на кнопку 'Реферальная программа'!"
        )
        return

    if not sites.get(site).get("can_give_for_free"):
        await query.message.answer(
            "❌ Эту площадку нельзя купить за реферальный дни\n\n<a href='https://telegra.ph/1'>Почему не на все площадки можно перенести подписку или купить за реферальные дни?</a>"
        )
        return

    await state.update_data(site=site)
    await state.update_data(day_referral=day_referral)
    await query.message.answer(
        f"▶️ Сколько дней подписки купить?\nДоступно: <b>{day_referral}</b>",
        reply_markup=cancel_button,
    )
    await state.set_state("buy_sub_ref_actions")


@router.message(StateFilter("buy_sub_ref_actions"))
async def buy_sub_ref_actions(msg: types.Message, state: FSMContext):
    state_data = await state.get_data()

    site = state_data.get("site")
    day_referral = state_data.get("day_referral")

    try:
        if not msg.text.isdigit():
            await msg.answer(
                f"▶️ Сколько дней подписки купить?\nДоступно: <b>{day_referral}</b>",
                reply_markup=cancel_button,
            )
            return
    except AttributeError:
        await msg.answer("❌ Что-то пошло не так, попробуйте еще раз")
        return

    if int(msg.text) <= 0:
        await msg.answer("❌ Недопустимо")
        return

    if int(msg.text) > int(day_referral):
        await msg.answer(f"❌ Вы не можете взять больше {day_referral} дней подписки")
        return

    await state.update_data(take_day=msg.text)

    await msg.answer(
        f"""
▶️ Площадка: {make_place_pretty_view(site)}
▶️ Время подписки: {msg.text} {correct_days_form(msg.text)}
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Купить",
                        callback_data="comfirm_sub_ref",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Отмена", callback_data="cancel_action"
                    ),
                ],
            ]
        ),
    )


@router.callback_query(F.data == "comfirm_sub_ref")
async def comfirm_sub_ref(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramAPIError):
        await query.answer()

    user_date = await state.get_data()
    site = user_date.get("site")
    take_day = user_date.get("take_day")
    if not take_day:
        await query.message.answer("❌ Ошибка")
        return

    day_referral = await db.get_user_referral_days(user_id=query.from_user.id)
    if int(day_referral) < int(take_day):
        await query.message.edit_text("❌ Недостаточно бонусных дней")
        return

    with suppress(TelegramAPIError):
        await query.message.delete()

    await db.set_referral_days(
        user_id=query.from_user.id, days=int(day_referral) - int(take_day)
    )
    new_expire_date = await db.add_subscription(
        site=site,
        new_expiry_date=datetime.now() + timedelta(days=int(take_day)),
        user_id=query.from_user.id,
    )

    await query.bot.send_video(
        chat_id=query.from_user.id,
        video=BANNER_VIDEO,
        caption=f"⏳ Подписка закончится: <b>{humanize_date_v2(await convert_to_user_timezone(new_expire_date, user_id=query.from_user.id))}</b>",
        reply_markup=get_place_access_btns(site),
    )
    await query.bot.send_message(
        chat_id=CHATS.get("logs"),
        text=f"""
#referral

▶️ Взял: <b>{query.from_user.mention_html()} / {query.from_user.id} / {query.from_user.username} </b>
▶️ Срок: <b>{take_day} дней </b>
▶️ Площадка: <b>{make_place_pretty_view(site)}</b>
    """,
    )

    await state.clear()
