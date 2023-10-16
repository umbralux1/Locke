from aiogram.filters import Filter
from aiogram.types import Message

from app import bot
from app.config import BANNER_VIDEO


class IsUserHasUsername(Filter):
    async def __call__(self, message: Message) -> bool:
        if message.from_user.username:
            return True

        await bot.send_video(
            chat_id=message.from_user.id,
            video=BANNER_VIDEO,
            caption="У вас не установлено имя пользователя. Установите его для корректной работы бота.",
        )
