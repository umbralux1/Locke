from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app import dp
from app.keyboards.blacklist_ads_menu import get_blacklist_ads_btns

router = Router()
dp.include_router(router)


@router.callback_query(F.data == "blacklist_ads")
async def blacklist_ads(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="Здесь вы можете настроить какие объявления вам не нужно показывать, т.е укажите категории, которые вам надо исключать.",
            reply_markup=await get_blacklist_ads_btns(query.from_user.id),
        )

    with suppress(TelegramAPIError):
        await query.answer()
