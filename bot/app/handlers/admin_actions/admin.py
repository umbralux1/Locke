import asyncio

from aiogram import types, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from app import dp
from app.config import BANNER_VIDEO
from app.filters.admin import IsAdmin
from app.misc.scheduler import proxy_check

router = Router()
dp.include_router(router)

flags = {"throttling_key": "default"}


@dp.message(F.text.in_({"🔧 Админка", "/adm"}), IsAdmin(), flags=flags)
async def administration_menu(msg: types.Message, state: FSMContext):
    await state.set_state(None)

    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="👤 Получить пользователя",
                        callback_data="get_user",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📬 Рассылка",
                        callback_data="admin_mailer",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📡 Проверка прокси",
                        callback_data="check_proxy",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🛡 Проверка всех площадок",
                        callback_data="check_sites",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 Сменить статус покупки площадки",
                        callback_data="change_buy_site_status",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📊 Получить кассовый отчет",
                        callback_data="get_cash_report",
                    )
                ],
            ]
        ),
        video=BANNER_VIDEO,
    )


@router.callback_query(F.data == "check_proxy", IsAdmin())
async def check_proxy(query: CallbackQuery):
    await query.message.answer("Ожидайте....")

    asyncio.create_task(proxy_check())
