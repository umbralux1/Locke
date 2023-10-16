import traceback
from contextlib import suppress
from datetime import datetime

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from app import dp, db
from app.handlers.admin_actions.get_user import get_user_
from app.keyboards.cancel import cancel_button
from app.keyboards.help_system_menu import ticket_operator_menu, ticket_user_menu
from app.misc.parser_essintials import encode_html

router = Router()
dp.include_router(router)


@router.callback_query(F.data == "take_ticket")
async def take_ticket(query: CallbackQuery):
    msg_text = query.message.text or query.message.caption
    ticket_id = msg_text.split()[0].replace("ID-", "")

    await db.update_ticket(
        ticket_status="considered",
        ticket_id=ticket_id,
        support_chat_id=query.from_user.id,
        support_username=query.from_user.username,
    )

    now = (
        datetime.now(tz=query.message.date.tzinfo)
        if query.message.date.tzinfo
        else datetime.now()
    )
    time_difference = now - query.message.date
    conf_text = f"{encode_html(msg_text.replace('@bebrabrbrbr', '').replace('@floatx46', ''))}\n\nОбработку тикета взял {query.from_user.mention_html()}\nТикет взят за {time_difference.total_seconds()} секунд(-у/-ы)"

    try:
        await query.message.edit_text(
            conf_text,
        )
    except TelegramAPIError:
        with suppress(TelegramBadRequest):
            await query.message.edit_caption(
                caption=conf_text,
            )

    await query.bot.send_message(
        chat_id=query.from_user.id,
        text=encode_html(msg_text),
        reply_markup=ticket_operator_menu,
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "getuser_ticket")
async def getuser_ticket(query: CallbackQuery, state: FSMContext):
    if query.message.text:
        ticket_id = query.message.text.split()[0].replace("ID-", "")
    else:
        ticket_id = query.message.caption.split()[0].replace("ID-", "")

    ticket_info = await db.get_ticket_info(ticket_id=ticket_id)
    chat_id = ticket_info[0].get("owner_chat_id")
    username = await db.get_username_by_id(int(chat_id))

    await get_user_(chat_id, username, query.message)

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "detail_ticket")
async def detail_ticket(query: CallbackQuery, state: FSMContext):
    try:
        if query.message.text:
            ticket_id = query.message.text.split()[0].replace("ID-", "")
        else:
            ticket_id = query.message.caption.split()[0].replace("ID-", "")

        ticket_info = await db.get_ticket_info(ticket_id=ticket_id)
        ticket_detail = ticket_info[0].get("ticket_detail")

        await query.message.answer(ticket_detail)
    except Exception:
        await query.message.answer("❌ Что-то пошло не так")
        return

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "close_ticket")
async def close_ticket(query: CallbackQuery, state: FSMContext):
    try:
        if query.message.text:
            ticket_id = query.message.text.split()[0].replace("ID-", "")
        else:
            ticket_id = query.message.caption.split()[0].replace("ID-", "")

        ticket_info = await db.get_ticket_info(ticket_id=ticket_id)
        chat_id = ticket_info[0].get("owner_chat_id")
        support_chat_id = ticket_info[0].get("support_chat_id")

        await state.update_data(ticket_id=ticket_id)
        await state.update_data(chat_id=chat_id)
        await state.update_data(support_chat_id=support_chat_id)
    except Exception:
        await query.message.answer("❌ Что-то пошло не так")
        return

    await query.message.answer(
        "Вы точно хотите закрыть тикет?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data="close_ticket_confirm",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "close_ticket_confirm")
async def close_ticket_confirm(query: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    ticket_id = state_data.get("ticket_id")
    chat_id = state_data.get("chat_id")
    support_chat_id = state_data.get("support_chat_id")

    await db.update_ticket_status(ticket_id=ticket_id, ticket_status="closed")
    await query.bot.send_message(
        chat_id=chat_id, text=f"Обращение #{ticket_id} закрыто"
    )
    await query.bot.send_message(
        chat_id=support_chat_id,
        text=f"Обращение #{ticket_id} закрыто",
    )
    await query.message.edit_text("Выполнена")

    await state.clear()

    with suppress(TelegramAPIError):
        await query.answer()


def resolve_agent_name_by_id(userid):
    if userid == 1:
        return "⚡️ Дмитрий"
    else:
        return "None"


@router.callback_query(F.data.in_({"write_msg_ticket", "user_write_msg_ticket"}))
async def write_msg_ticket(query: CallbackQuery, state: FSMContext):
    try:
        if query.message.text:
            ticket_id = query.message.text.split()[0].replace("ID-", "")
        else:
            ticket_id = query.message.caption.split()[0].replace("ID-", "")

        ticket_info = await db.get_ticket_info(ticket_id=ticket_id)
        if query.data == "write_msg_ticket":
            chat_id = ticket_info[0].get("owner_chat_id")
            next_state = "answer_msg_to_owner_ticket"
        else:
            chat_id = ticket_info[0].get("support_chat_id")
            next_state = "user_answer_msg_to_support"
    except Exception:
        logger.debug(traceback.format_exc())
        await query.message.answer("❌ Что-то пошло не так")
        return

    ticket_status = ticket_info[0].get("ticket_status")
    if ticket_status == "closed":
        with suppress(TelegramAPIError):
            await query.message.delete()
            return

    await state.update_data(chat_id=chat_id)
    await state.update_data(ticket_id=ticket_id)
    await query.message.answer(
        "📝Введите сообщение. Если необходимо, то прикрепите файл или изображения.",
        reply_markup=cancel_button,
    )
    await state.set_state(next_state)

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(
    StateFilter("answer_msg_to_owner_ticket", "user_answer_msg_to_support"),
)
async def answer_msg_ticket(msg: types.Message, state: FSMContext):
    user_data = await state.get_data()
    current_state = await state.get_state()
    chat_id = user_data.get("chat_id")
    if not chat_id:
        await msg.answer("❌ Что-то пошло не так")
        return

    ticket_id = user_data.get("ticket_id")

    if msg.text and len(msg.text) > 4096:
        await msg.answer("❌ Слишком длинное сообщение")
        return

    if msg.caption and len(msg.caption) > 1024:
        await msg.answer("❌ Слишком длинное сообщение")
        return

    if current_state == "answer_msg_to_owner_ticket":
        agent_name = resolve_agent_name_by_id(msg.from_user.id)
        reply_markup = ticket_user_menu
    else:
        agent_name = msg.from_user.mention_html()
        reply_markup = ticket_operator_menu

    if msg.text:
        await msg.bot.send_message(
            chat_id,
            f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.text)}</b>",
            reply_markup=reply_markup,
        )
    elif msg.photo:
        await msg.bot.send_photo(
            chat_id,
            msg.photo[-1].file_id,
            caption=f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.caption)}</b>",
            reply_markup=reply_markup,
        )
    elif msg.video:
        await msg.bot.send_video(
            chat_id,
            msg.video.file_id,
            caption=f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.caption)}</b>",
            reply_markup=reply_markup,
        )
    elif msg.document:
        await msg.bot.send_document(
            chat_id,
            msg.document.file_id,
            caption=f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.caption)}</b>",
            reply_markup=reply_markup,
        )
    elif msg.audio:
        await msg.bot.send_audio(
            chat_id,
            msg.audio.file_id,
            caption=f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.caption)}</b>",
            reply_markup=reply_markup,
        )
    elif msg.voice:
        await msg.bot.send_voice(
            chat_id,
            msg.voice.file_id,
            caption=f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.caption)}</b>",
            reply_markup=reply_markup,
        )
    elif msg.animation:
        await msg.bot.send_animation(
            chat_id,
            msg.animation.file_id,
            caption=f"ID-{ticket_id}\n\n{agent_name}: <b>{encode_html(msg.caption)}</b>",
            reply_markup=reply_markup,
        )
    else:
        await msg.answer("❌ Бот не поддерживает этот формат сообщения")
        return

    await msg.answer(f"Успешно отправлено\n\nID-{ticket_id}")
    await state.clear()
