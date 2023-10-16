from contextlib import suppress

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.config import CHATS
from app.filters.admin import IsAdmin
from app.keyboards.cancel import cancel_button

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("add_referral_days"))
async def add_referral_days(query: CallbackQuery, state: FSMContext):
    user_id = query.data.split("|")[-1]

    await state.update_data(user_id=user_id)
    await query.message.answer(
        "▶️ Сколько реферальных дней начислить?", reply_markup=cancel_button
    )
    await state.set_state("get_referral")

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("get_referral"))
async def get_referral(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        await msg.answer("Нужно число")
        return

    user_data = await state.get_data()
    await state.update_data(days_referal=msg.text)

    await msg.answer(
        f"""
▶️ Пользователь: ID-{user_data.get("user_id")}
▶️ Кол-во дней: {msg.text}
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Начислить",
                        callback_data="confirm_admin_ref_add",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data == "confirm_admin_ref_add", IsAdmin())
async def confirm_referral_admin(query: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    day_referral = await db.get_user_referral_days(
        user_id=int(user_data.get("user_id"))
    )
    await db.set_referral_days(
        user_id=int(user_data.get("user_id")),
        days=int(day_referral) + int(user_data.get("days_referal")),
    )

    await query.bot.send_message(
        chat_id=CHATS.get("logs"),
        text=f"""
#admin_sub_refferal_days

▶️ Админ: <b>{query.from_user.mention_html()}</b>
▶️ Выдал: <b>ID-{user_data.get("user_id")}</b>
▶️ Срок: <b>{user_data.get("days_referal")} реферальных дней</b>""",
    )

    await query.message.edit_text("✅ Успешно начислено")

    with suppress(TelegramAPIError):
        await query.answer()
