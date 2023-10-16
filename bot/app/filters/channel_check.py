from aiogram import types
from aiogram.filters import Filter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app import bot
from app.config import CHATS, BANNER_VIDEO


class IsUserInNewsChannel(Filter):
    async def __call__(self, message: types.Message):
        member = await bot.get_chat_member(
            chat_id=CHATS.get("news"), user_id=message.from_user.id
        )

        if member.status in ["administrator", "member", "creator"]:
            return True

        await bot.send_video(
            chat_id=message.from_user.id,
            video=BANNER_VIDEO,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Вступить в канал", url="https://t.me/1"
                        ),
                    ]
                ]
            ),
        )
