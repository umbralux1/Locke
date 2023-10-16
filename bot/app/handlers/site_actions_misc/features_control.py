from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery

from app import dp, db
from app.keyboards.site_actions import get_site_actions_btns

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("add_to_features"))
async def add_to_features(query: CallbackQuery):
    site = query.data.split("|")[-1]

    await db.add_user_feature(user_id=query.from_user.id, site=site)

    with suppress(TelegramBadRequest):
        await query.message.edit_reply_markup(
            reply_markup=get_site_actions_btns(
                is_feature=await db.get_user_features(user_id=query.from_user.id),
                site=site,
            )
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_from_features"))
async def delete_from_features(query: CallbackQuery):
    site = query.data.split("|")[-1]

    await db.delete_user_feature(user_id=query.from_user.id, site=site)
    await query.message.edit_reply_markup(
        reply_markup=get_site_actions_btns(
            is_feature=await db.get_user_features(user_id=query.from_user.id),
            site=site,
        )
    )

    with suppress(TelegramAPIError):
        await query.answer()
