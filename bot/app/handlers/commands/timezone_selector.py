from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import dp, db
from app.config import TIMEZONE_CONFIG
from app.filters.private_chat import IsPrivate
from app.filters.username import IsUserHasUsername

router = Router()
dp.include_router(router)


flags = {"throttling_key": "default"}


@router.message(Command("timezone"), IsPrivate(), IsUserHasUsername(), flags=flags)
async def select_timezone(msg: Message):
    timezone_keyboard = InlineKeyboardBuilder()
    utc_shifts = dict(
        sorted(
            TIMEZONE_CONFIG.items(),
            key=lambda item: float(item[0].replace("UTC", "")),
        )
    )

    buttons = []
    for shift in utc_shifts:
        button = InlineKeyboardButton(text=shift, callback_data=f"set_timezone|{shift}")
        buttons.append(button)
        if len(buttons) == 3:
            timezone_keyboard.row(*buttons)
            buttons = []

    # Добавляем оставшиеся кнопки, если их число меньше трех
    if buttons:
        timezone_keyboard.row(*buttons)

    timezone_keyboard.adjust(3)
    await msg.answer(
        f"Выберите ваш сдвиг по UTC:\n\nЭто нужно для корректировки отображений всех дат и времени, посмотреть вашу временную зону можно здесь - https://time.is/your_time_zone\n\nТекущий часовой пояс - {await db.get_timezone(msg.from_user.id)}",
        reply_markup=timezone_keyboard.as_markup(),
    )


@router.callback_query(F.data.contains("set_timezone"))
async def set_timezone(query: CallbackQuery):
    shift = query.data.split("|")[-1]
    timezone = TIMEZONE_CONFIG.get(shift)

    await db.update_timezone(query.from_user.id, timezone)

    await query.message.answer(
        f"✅ Ваша временная зона {shift} успешно установлена!\n\nСменить временную зону вы можете всегда через команду /timezone"
    )
