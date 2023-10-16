import asyncio
from contextlib import suppress

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.deep_linking import create_start_link

from app import dp, db, bot
from app.config import WHATSAPP_CHECK_LIMIT_PER_DAY, BANNER_VIDEO
from app.filters.admin import IsAdmin
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.settings_menu import get_configuration_str_for_share
from app.misc.scheduler import (
    reminder_proxy_target_proxy,
    reminder_proxy6,
    reminder_proxy_seller_io,
    reminder_server,
)
from app.misc.time_declension import humanize_date

router = Router()
dp.include_router(router)


async def gen_getuser_btns(user_id):
    status_ban = await db.get_tp_ban_status(user_id=int(user_id))
    ban_text = "Разбанить в ТП" if status_ban else "Забанить в ТП"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выдать подписку",
                    callback_data=f"admin_subscription|{user_id}|give",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Забрать подписку",
                    callback_data=f"admin_subscription|{user_id}|take",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Начислить реферальные дни",
                    callback_data=f"add_referral_days|{user_id}",
                )
            ],
            # [
            #     InlineKeyboardButton(
            #         text="🔄 Сбросить лимит WA",
            #         callback_data="pass",
            #     )
            # ],
            # [
            #     InlineKeyboardButton(
            #         text="🛑 Остановить парсер",
            #         callback_data="pass",
            #     )
            # ],
            [
                InlineKeyboardButton(
                    text=ban_text,
                    callback_data=f"tp_ban_status_change|{user_id}",
                )
            ],
        ]
    )


@router.callback_query(F.data.contains("tp_ban_status_change"))
async def tp_ban_status_change(query: CallbackQuery, state: FSMContext):
    user_id = query.data.split("|")[-1]

    status_ban = await db.get_tp_ban_status(user_id=int(user_id))
    if status_ban:
        await db.set_tp_ban_status_user(user_id=int(user_id), status=False)
        await query.message.edit_reply_markup(
            reply_markup=await gen_getuser_btns(user_id)
        )
        await query.answer("✅ Успешно разбанен", show_alert=True)
    else:
        await db.set_tp_ban_status_user(user_id=int(user_id), status=True)
        with suppress(TelegramAPIError):
            await query.message.edit_reply_markup(
                reply_markup=await gen_getuser_btns(user_id)
            )
        await query.answer("✅ Успешно забанен", show_alert=True)

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "get_user", IsAdmin())
async def get_user(query: CallbackQuery, state: FSMContext):
    await query.message.answer("Введи id/username пользователя")
    await state.set_state("get_user")


async def get_user_(chat_id_user, username, msg):
    msg_text = ""
    if not chat_id_user:
        await msg.answer("Что-то пошло не так, попробуйте еще раз")
        return

    referral_id = await db.get_user_referral_by_id(int(chat_id_user))
    referral_username = ""
    if referral_id:
        referral_username = f"@{await db.get_username_by_id(int(referral_id))}"
        referral_username = f"▶️ Пользователь является рефералом: <b>{referral_username}/ID-{referral_id}</b>"

    referrals_count = await db.count_user_referrals(int(chat_id_user)) or 0

    subs = await db.get_all_user_subscription_site(user_id=int(chat_id_user))
    for sub in subs:
        site = sub.get("site")
        expiry_date = sub.get("expiry_date")
        msg_text += f"<b>{make_place_pretty_view(site)}</b>, подписка истечет через <b>{humanize_date(expiry_date, add_word=False)} ({expiry_date.strftime('%d.%m.%Y %H:%M')})</b>\n"

    configuration_settings = await db.get_configuration_settings(
        user_id=int(chat_id_user)
    )
    if configuration_settings is None:
        await msg.answer("❌ Пропишите /start и попробуй заново")
        return

    configuration = await create_start_link(
        payload=get_configuration_str_for_share(configuration_settings[0]), bot=bot
    )

    push_text = f"""
▶️ Пользователь: <b>@{username}/ID-{chat_id_user}</b>
▶️ Кол-во реферальных дней: <b>{await db.get_user_referral_days(user_id=int(chat_id_user))}</b>
▶️ Кол-во рефералов: <b>{referrals_count}</b>
▶️ Конфигуратор: <b>{configuration}CFG</b>
▶️ Часовой пояс: <b>{await db.get_timezone(int(chat_id_user))}</b>
▶️ WA кредиты: <b>0/{WHATSAPP_CHECK_LIMIT_PER_DAY}</b>
▶️ Статус парсинга: <b>0</b>
{referral_username}

▶️ Активные подписки:
{msg_text}
    """
    if len(push_text) > 4096:
        for x in range(0, len(push_text), 4096):
            await msg.bot.send_video(
                video=BANNER_VIDEO,
                chat_id=msg.chat.id,
                caption=push_text[x : x + 4096].replace("<b>", "").replace("</b>", ""),
                reply_markup=await gen_getuser_btns(chat_id_user),
            )
    else:
        await msg.bot.send_video(
            video=BANNER_VIDEO,
            chat_id=msg.chat.id,
            caption=push_text,
            reply_markup=await gen_getuser_btns(chat_id_user),
        )


@router.message(Command("getuser"), IsAdmin())
@router.message(StateFilter("get_user"))
async def get_user_handler(msg: types.Message, state: FSMContext):
    chat_id_or_username = msg.text.split()[-1]
    if chat_id_or_username == "me":
        chat_id_or_username = msg.from_user.username

    if chat_id_or_username.isdigit():
        chat_id_user = chat_id_or_username
        username = await db.get_username_by_id(int(chat_id_or_username))
    else:
        username = chat_id_or_username.replace("@", "")
        chat_id_user = await db.get_id_by_username(username)

    if not username:
        await msg.answer("Пользователь не найден")
        return

    await get_user_(chat_id_user, username, msg)


@router.message(Command("expire_proxy"), IsAdmin())
async def expire_proxy(msg: types.Message, state: FSMContext):
    asyncio.create_task(reminder_proxy_target_proxy())
    asyncio.create_task(reminder_proxy6())
    asyncio.create_task(reminder_proxy_seller_io())
    asyncio.create_task(reminder_server())


@router.message(Command("help"), IsAdmin())
async def help_show(msg: types.Message, state: FSMContext):
    await msg.answer(
        """Что ты здесь забыл сталкер ?

getuser - получить пользователя
mailer - рассылка
getday - получить кассу за день
getmonth - получить кассу за месяц
check_proxy - прочекать прокси на валид
clear_redis - очистить редиску
expire_proxy - проверить прокси че там продлять надо или нет
"""
    )
