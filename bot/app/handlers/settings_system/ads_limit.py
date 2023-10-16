from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
)
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.config import LIMIT_ADS_MAX, LIMIT_ADS_MIN, BANNER_VIDEO
from app.keyboards.cancel import cancel_button

return_to_settings_btns = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀",
                callback_data="return_to_settings",
            )
        ],
    ]
)

router = Router()
dp.include_router(router)


@router.callback_query(F.data == "set_getter_ads_limit")
async def set_getter_ads_limit(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption=f"""Сейчас установлено: <b>{await db.get_getter_ads_limit(query.from_user.id)}</b>
    
— Парсер будет оптимизировать выдачу объявлений, стремясь к установленному Вами максимальному количеству

ℹ️ <b>Введите желаемое количество объявлений [{LIMIT_ADS_MIN}-{LIMIT_ADS_MAX}]:</b>""",
            reply_markup=return_to_settings_btns,
        )

    await state.set_state("get_getter_ads_limit")

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("get_getter_ads_limit"))
async def get_getter_ads_limit(msg, state: FSMContext):
    ads_limit = msg.text

    if not ads_limit.isdigit():
        await msg.answer("❌ Введите число", reply_markup=cancel_button)
        return

    if int(ads_limit) < LIMIT_ADS_MIN or int(ads_limit) > LIMIT_ADS_MAX:
        await msg.answer(
            f"❌ Введите число от {LIMIT_ADS_MIN} до {LIMIT_ADS_MAX}",
            reply_markup=cancel_button,
        )
        return

    await db.update_user_setting(msg.from_user.id, "getter_ads_limit", int(ads_limit))

    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        reply_markup=return_to_settings_btns,
        video=BANNER_VIDEO,
        caption=f"""Сейчас установлено: <b>{await db.get_getter_ads_limit(msg.from_user.id)}</b>
    
— Парсер будет оптимизировать выдачу объявлений, стремясь к установленному Вами максимальному количеству

ℹ️ <b>Введите желаемое количество объявлений [{LIMIT_ADS_MIN}-{LIMIT_ADS_MAX}]:</b>""",
    )

    await state.clear()
    await state.set_state("get_getter_ads_limit")
