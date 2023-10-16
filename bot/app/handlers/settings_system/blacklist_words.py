from contextlib import suppress

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app import dp, db
from app.config import BANNER_VIDEO
from app.keyboards.cancel import cancel_button

blacklisted_words_btns = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Добавить новое слово",
                callback_data="add_new_blacklist_word",
            )
        ],
        [
            InlineKeyboardButton(
                text="🗑 Очистить список слов",
                callback_data="clear_blacklist_words",
            )
        ],
        [
            InlineKeyboardButton(
                text="◀",
                callback_data="return_to_settings",
            )
        ],
    ]
)

TEXT_TEMPLATE = """<b>Введённые вами слова будут проверяться в названии и описании товара, если будет совпадение - объявление не будет выдано</b>

<b>Ваши слова:</b>
<code>$words</code>"""

router = Router()
dp.include_router(router)


async def get_words(state, user_id):
    words = await db.get_user_blacklisted_words(user_id)
    if words is None:
        words = ""
    await state.update_data(words=words)
    return words


async def send_photo_with_words(bot, chat_id, words):
    show_words = words[:512] + "\n..." if len(words) >= 512 else words
    await bot.send_video(
        caption=TEXT_TEMPLATE.replace("$words", show_words[1:]),
        chat_id=chat_id,
        reply_markup=blacklisted_words_btns,
        video=BANNER_VIDEO,
    )


@router.callback_query(F.data == "blacklist_words")
async def blacklist_words(query: CallbackQuery, state: FSMContext):
    words = await get_words(state, query.from_user.id)
    show_words = words[:512] + "\n..." if len(words) >= 512 else words
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption=TEXT_TEMPLATE.replace("$words", show_words[1:]),
            reply_markup=blacklisted_words_btns,
        )
    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "add_new_blacklist_word")
async def add_new_blacklist_word(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="🔧 Введите слово для добавления в чёрный список",
            reply_markup=cancel_button,
        )

    await state.set_state("add_new_blacklist_word")

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("add_new_blacklist_word"))
async def add_new_blacklist_word(msg: types.Message, state: FSMContext):
    text = msg.text

    if len(text) > 4096:
        await msg.answer("❌ Слишком много символов")
        return

    state_data = await state.get_data()
    words = state_data.get("words") + "\n" + text

    await db.add_blacklisted_word(user_id=msg.from_user.id, words=words)

    words = await get_words(state, msg.from_user.id)

    await send_photo_with_words(msg.bot, msg.from_user.id, words)


@router.callback_query(F.data == "clear_blacklist_words")
async def clear_blacklist_words(query: CallbackQuery, state: FSMContext):
    await query.message.answer(
        "Вы точно хотите удалить все ваши слова?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data="clear_blacklist_words_confirm",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "clear_blacklist_words_confirm")
async def clear_blacklist_words_confirm(query: CallbackQuery, state: FSMContext):
    await db.delete_user_blacklisted_words(query.from_user.id)

    words = await get_words(state, query.from_user.id)

    await send_photo_with_words(query.bot, query.from_user.id, words)

    with suppress(TelegramAPIError):
        await query.answer()
