from contextlib import suppress
from urllib.parse import unquote_plus

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from loguru import logger

from app import dp, db
from app.config import (
    CUSTOM_TEXT_LIMIT,
    CUSTOM_TEXT_NAME_LENGTH_LIMIT,
    CUSTOM_TEXT_LIMIT_LENGTH,
    CUSTOM_TEXT_OFFSET_LIMIT,
    BANNER_VIDEO,
)
from app.keyboards.cancel import cancel_button
from app.keyboards.custom_text_menu import (
    get_user_custom_text_buttons,
    get_item_custom_msg_actions,
)

SUPPORTED_TAG = ["@link", "@sellername", "@price", "@itemname"]

router = Router()
dp.include_router(router)


def format_user_text(user_text: str, text_title: str):
    user_text = unquote_plus(user_text)

    if any(word in unquote_plus(user_text) for word in SUPPORTED_TAG):
        user_text = f"<code>{user_text}</code>\n\n<b>Пример отображения:</b>\n{user_text.replace('@link', '<i>https://www.google.com/</i>').replace('@sellername', '<i>Михаил</i>').replace('@price', '<i>1000 EUR</i>').replace('@itemname', '<i>iPHONE</i>')}"
    else:
        user_text = f"<code>{user_text}</code>"

    return f"""
Название текста: <b>{text_title}</b>
Текст: {user_text}
"""


@router.callback_query(F.data.contains("custom_text"))
async def custom_text(query: CallbackQuery, state):
    site = query.data.split("|")[-1]

    await state.update_data(show_callback=None)

    user_text = await db.get_custom_msg_text(query.from_user.id, site)
    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption="🔽 Выберите нужный вам текст\n\n<a href='https://telegra.ph/1'>Что такое кастомный текст и как он работает?</a>",
            reply_markup=get_user_custom_text_buttons(site, user_text=user_text),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("confirm_delete_all_ct"))
async def delete_all_ct_confirm(query: CallbackQuery):
    site = query.data.split("|")[-1]

    await db.delete_custom_msg_text(query.from_user.id, site)

    user_text = await db.get_custom_msg_text(query.from_user.id, site)
    with suppress(TelegramAPIError):
        await query.bot.send_video(
            video=BANNER_VIDEO,
            chat_id=query.from_user.id,
            caption="🔽 Выберите нужный вам текст\n\n<a href='https://telegra.ph/1'>Что такое кастомный текст и как он работает?</a>",
            reply_markup=get_user_custom_text_buttons(
                site, user_text=user_text, sender_select=True
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_all_ct"))
async def delete_all_custom_texts(query: CallbackQuery):
    site = query.data.split("|")[-1]

    await query.message.answer(
        "Вы точно хотите удалить все ваши кастомные текста?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data=f"confirm_delete_all_ct|{site}",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("add_ct"))
async def add_custom_text(query: CallbackQuery, state: FSMContext):
    site = query.data.split("|")[-1]

    await query.message.edit_caption(
        caption="""
✏️ Введите ваш новый кастомный текст

<b>Доступные слова вставки:</b>
<code>@link</code> - Подставит текущую ссылку
<code>@sellername</code> - Подставит имя продвца
<code>@price</code> - Подставит цена товара
<code>@itemname</code> - Подставит название товара

▶️ <b>Вы можете указать слово вставку и вместо него подставится нужная информация конкретного товара</b>
""",
        reply_markup=cancel_button,
    )

    await state.update_data(site=site)
    await state.set_state("get_body_custom_text")

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("get_body_custom_text"))
async def get_body_custom_text(msg: Message, state: FSMContext):
    state_data = await state.get_data()
    site = state_data.get("site")

    user_text = await db.get_custom_msg_text(site=site, user_id=msg.from_user.id)
    if len(user_text) > CUSTOM_TEXT_LIMIT:
        await msg.answer(
            "❌ Слишком много кастомных текстов", reply_markup=cancel_button
        )
        return

    if not await get_user_text_and_check_length(msg, site, CUSTOM_TEXT_LIMIT_LENGTH):
        return

    await state.update_data(text_body=msg.text)
    await msg.answer("💾 Введи краткое название твоего текста")
    await state.set_state("get_title_custom_text")


def validation_user_text(text):
    if text is None:
        return text

    return (
        text.replace("<", "")
        .replace(">", "")
        .replace("'", "")
        .replace('"', "")
        .replace(";", "")
        .replace("~", "")
        .replace(":", "")
        .strip()
    )


@router.message(StateFilter("get_title_custom_text"))
async def get_title_custom_text(msg: Message, state: FSMContext):
    if len(msg.text) > CUSTOM_TEXT_NAME_LENGTH_LIMIT:
        await msg.answer("❌ Слишком длинное название", reply_markup=cancel_button)
        return

    await state.update_data(name=validation_user_text(msg.text))

    state_data = await state.get_data()
    site = state_data.get("site")
    text_title = state_data.get("name")
    text_body = state_data.get("text_body")
    show_callback = state_data.get("show_callback")

    text_exists = await db.get_custom_msg_text_by_title(
        msg.from_user.id, site, text_title
    )
    if text_exists:
        await msg.answer("❌ Такое название уже существует", reply_markup=cancel_button)
        return

    await db.add_custom_msg_text(
        user_id=msg.from_user.id,
        site=site,
        text_body=text_body,
        text_title=text_title,
    )
    user_text = await db.get_custom_msg_text(msg.from_user.id, site)

    if show_callback:
        sender_select = True
        await state.set_state(None)
    else:
        sender_select = False
        await state.clear()

    with suppress(TelegramAPIError):
        await msg.bot.send_video(
            video=BANNER_VIDEO,
            chat_id=msg.from_user.id,
            caption="🔽 Выберите нужный вам текст\n\n<a href='https://telegra.ph/1'>Что такое кастомный текст и как он работает?</a>",
            reply_markup=get_user_custom_text_buttons(
                site,
                user_text=user_text,
                sender_select=sender_select,
                show_callback=show_callback,
            ),
        )


@router.callback_query(F.data.contains("show_ct"))
async def show_ct(query: CallbackQuery, state: FSMContext):
    site = query.data.split("|")[-1]
    text_title = query.data.split("|")[-2]

    user_text = await db.get_custom_msg_text_by_title(
        site=site,
        user_id=query.from_user.id,
        text_title=text_title,
    )

    user_text = unquote_plus(user_text)
    text_body = unquote_plus(user_text)

    user_text = format_user_text(user_text, text_title)

    try:
        await query.message.edit_caption(
            caption=user_text[:1044],
            reply_markup=get_item_custom_msg_actions(site, text_title, text_body),
        )
    except TelegramBadRequest:
        await query.message.answer("текст слишком длинный, обратитесь в тп за помощью")
        logger.debug(user_text)
        logger.debug(get_item_custom_msg_actions(site, text_title, text_body))

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("edit_text_custom"))
async def edit_text_custom(query: CallbackQuery, state: FSMContext):
    site = query.data.split("|")[-2]
    text_title = query.data.split("|")[-1]

    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="▶️ Введите новый текст", reply_markup=cancel_button
        )

    await state.update_data(site=site)
    await state.update_data(text_title=text_title)
    await state.set_state("edit_text_get_new_text")

    with suppress(TelegramAPIError):
        await query.answer()


async def get_user_text_and_check_length(msg, site, len_limit):
    user_text = await db.get_custom_msg_text(site=site, user_id=msg.from_user.id)

    summar_len = CUSTOM_TEXT_OFFSET_LIMIT
    for row in user_text:
        text_title_, text_body_ = row
        summar_len += len(text_title_)
        summar_len += len(unquote_plus(text_body_))

    if summar_len + len(msg.text) > len_limit:
        await msg.answer(
            "❌ У вас слишком длинные текста, удалите пару заготовленных текстов или сократите текст текущих",
            reply_markup=cancel_button,
        )
        return False

    return True


@router.message(StateFilter("edit_text_get_new_text"))
async def edit_text_get_new_text(msg: Message, state: FSMContext):
    state_data = await state.get_data()
    site = state_data.get("site")
    text_title = state_data.get("text_title")

    if not await get_user_text_and_check_length(msg, site, CUSTOM_TEXT_LIMIT_LENGTH):
        return

    await db.add_custom_msg_text(
        user_id=msg.from_user.id,
        site=site,
        text_body=msg.text,
        text_title=text_title,
    )

    user_text = format_user_text(msg.text, text_title)

    await state.clear()
    await msg.bot.send_video(
        caption=user_text,
        chat_id=msg.from_user.id,
        reply_markup=get_item_custom_msg_actions(site, text_title, msg.text),
        video=BANNER_VIDEO,
    )


@router.callback_query(F.data.contains("confirm_delete_current_ct"))
async def confirm_delete_current_ct(query: CallbackQuery):
    site = query.data.split("|")[-2]
    text_title = query.data.split("|")[-1]

    await db.delete_custom_msg_text_by_title(query.from_user.id, site, text_title)

    user_text = await db.get_custom_msg_text(query.from_user.id, site)
    with suppress(TelegramAPIError):
        await query.bot.send_video(
            video=BANNER_VIDEO,
            chat_id=query.from_user.id,
            caption="🔽 Выберите нужный вам текст\n\n<a href='https://telegra.ph/1'>Что такое кастомный текст и как он работает?</a>",
            reply_markup=get_user_custom_text_buttons(site, user_text=user_text),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_current_ct"))
async def delete_current_ct(query: CallbackQuery):
    site = query.data.split("|")[-2]
    text_title = query.data.split("|")[-1]

    await query.message.answer(
        f"Вы точно хотите удалить {text_title}?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data=f"confirm_delete_current_ct|{site}|{text_title}",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()
