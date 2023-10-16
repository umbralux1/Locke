import asyncio
import re
from contextlib import suppress
from typing import Union

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from loguru import logger

from app import dp, db
from app.filters.admin import IsAdmin

router = Router()
dp.include_router(router)


@router.callback_query(F.data == "admin_mailer", IsAdmin())
@router.message(Command("mailer"), IsAdmin())
async def admin_mailer_handler(event: Union[CallbackQuery, Message], state: FSMContext):
    if isinstance(event, CallbackQuery):
        await event.message.answer("Введите текст/фото что нужно разослать")
    else:
        await event.answer("Введите текст/фото что нужно разослать")

    await state.set_state("get_mail_text")


@router.message(StateFilter("get_mail_text"))
async def get_mail_text(msg: Message, state: FSMContext):
    def func_selector():
        if msg.text:
            return msg.bot.send_message, {"text": msg.html_text}
        elif msg.photo:
            return msg.bot.send_photo, {
                "photo": msg.photo[-1].file_id,
                "caption": msg.caption,
            }
        elif msg.video:
            return msg.bot.send_video, {
                "video": msg.video.file_id,
                "caption": msg.caption,
            }
        elif msg.animation:
            return msg.bot.send_animation, {
                "animation": msg.animation.file_id,
                "caption": msg.caption,
            }
        else:
            return None, None

    mail_func, kwargs = func_selector()
    if not mail_func:
        await msg.answer("❌ Бот не поддерживает этот формат сообщения")
        return

    await state.update_data(
        content_type=msg.content_type,
        text=msg.html_text
        if msg.text
        else None,  # Используйте проверку на наличие текста перед вызовом html_text
        file_id=(msg.photo[-1].file_id if msg.photo else None),
        caption=msg.caption,
    )

    await mail_func(
        msg.from_user.id,
        **kwargs,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Разослать всем",
                        callback_data="admin_mailer_confirm",
                    )
                ]
            ]
        ),
    )


@router.callback_query(F.data == "admin_mailer_confirm", IsAdmin())
async def admin_mailer_confirm(query: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    content_type = state_data.get("content_type")
    text = state_data.get("text")
    file_id = state_data.get("file_id")
    caption = state_data.get("caption")

    if content_type == "text":
        mail_func, kwargs = query.bot.send_message, {"text": text}
    elif content_type == "photo":
        mail_func, kwargs = query.bot.send_photo, {"photo": file_id, "caption": caption}
    elif content_type == "video":
        mail_func, kwargs = query.bot.send_video, {"video": file_id, "caption": caption}
    elif content_type == "animation":
        mail_func, kwargs = query.bot.send_animation, {
            "animation": file_id,
            "caption": caption,
        }
    else:
        await query.message.answer("❌ Unexpected error during mail processing.")
        return

    all_users_id = await db.get_all_users_id()
    stats_msg = await query.message.answer(
        f"Рассылка началась\n\nСтатус рассылки - 0/{len(all_users_id)}"
    )

    await state.clear()

    async def mail_start():
        stats_msg_text = stats_msg.text

        for user in all_users_id:
            chat_id = user.get("user_id")
            logger.debug(chat_id)

            with suppress(TelegramAPIError):
                await mail_func(chat_id, **kwargs)

            match = re.search(r"(\d+)/", stats_msg_text)
            current_value = int(match[1])
            incremented_value = current_value + 1
            stats_msg_text = stats_msg_text.replace(
                f"{current_value}/", f"{incremented_value}/", 1
            )

            await stats_msg.edit_text(stats_msg_text)
            await asyncio.sleep(1)

    asyncio.create_task(mail_start())
