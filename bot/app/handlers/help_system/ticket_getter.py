import asyncio
from contextlib import suppress

import numpy as np
from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app import dp, db
from app.config import CHATS, BANNER_VIDEO
from app.filters.channel_check import IsUserInNewsChannel
from app.filters.private_chat import IsPrivate
from app.filters.username import IsUserHasUsername
from app.keyboards.cancel import cancel_button
from app.misc.parser_essintials import encode_html, pool_thread

ARTICLES_DICT = {
    "Как сменить площадку": "https://telegra.ph/1",
    "Как парсить без токенов": "https://telegra.ph/1",
    "Не работает/Не парсит": "https://telegra.ph/1",
    "Как подарить/перенести подписку на другой аккаунт": "https://telegra.ph/1",
    "Можно ли оплатить через метод оплаты, которого у нас нет": "https://telegra.ph/1",
    "Можно ли вернуть деньги (манибек) за подписку": "https://telegra.ph/1",
    "Как очистить текста для авторассылки": "https://telegra.ph/1",
}

router = Router()
dp.include_router(router)


def find_best_matches_vectorized(user_query, articles_dict, top_n=5):
    vectorized = TfidfVectorizer()
    articles = list(articles_dict.keys())

    texts = [user_query] + articles
    tfidf_matrix = vectorized.fit_transform(texts)

    cosine_similarities = cosine_similarity(
        tfidf_matrix[:1], tfidf_matrix[1:]
    ).flatten()
    best_match_idx = np.argsort(-cosine_similarities)

    return [(articles[i], articles_dict[articles[i]]) for i in best_match_idx[:top_n]]


async def find_best_matches_vectorized_async(user_query, articles_dict, top_n=5):
    return find_best_matches_vectorized(user_query, articles_dict, top_n)
    # return await asyncio.get_event_loop().run_in_executor(
    #     pool_thread, find_best_matches_vectorized, user_query, articles_dict, top_n
    # )


flags = {"throttling_key": "default"}


@dp.message(
    F.text == "🆘 Помощь",
    IsPrivate(),
    IsUserHasUsername(),
    IsUserInNewsChannel(),
    flags=flags,
)
async def help_handler(msg: types.Message, state: FSMContext):
    await state.set_state(None)

    status_ban = await db.get_tp_ban_status(user_id=msg.from_user.id)
    if status_ban:
        await msg.answer(
            "К сожалению, вам пока запретили подавать тикеты в ТП, возможно это из-за флуда"
        )
        return

    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Создать тикет",
                        callback_data="create_ticket",
                    )
                ],
            ]
        ),
        video=BANNER_VIDEO,
        caption="""
🤔 <b>Возникли вопросы, проблемы или предложения?</b>

👩‍💻<b>Свяжитесь с нами,</b> используя кнопку ниже, и <b>наши специалисты примутся за решение вашего вопроса!</b>

🤖 Отмечаем, что наш бот оснащен базой ответов и стремится решить Ваш вопрос, не вовлекая в процесс специалиста.
""",
    )


@router.callback_query(F.data == "create_ticket")
async def create_ticket(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="""
📝 Опишите обращение  <b>максимально подробно.</b>

Если Вы столкнулись с технической проблемой на площадке:

<b>1️⃣ Укажите название площадки.
2️⃣ Предоставьте ссылку на конфигуратор лога.
3️⃣ Поделитесь статистикой по завершении парсинга.</b>

Таким образом, мы сможем оперативно помочь вам! 🚀
""",
            reply_markup=cancel_button,
        )

    with suppress(TelegramAPIError):
        await query.answer()

    await state.set_state("create_ticket")


@router.message(StateFilter("create_ticket"))
async def create_ticket_handler(msg: types.Message, state: FSMContext):
    skip_faq = not msg.text
    if not skip_faq:
        best_matches = await find_best_matches_vectorized_async(
            msg.text, ARTICLES_DICT, top_n=3
        )
        # logger.debug(best_matches)

    text = msg.text or msg.caption or "*"

    supported_content_types = {
        "text": ("text", "text"),
        "photo": ("file_id", "photo"),
        "video": ("file_id", "video"),
        "document": ("file_id", "document"),
        "audio": ("file_id", "audio"),
        "voice": ("file_id", "voice"),
        "animation": ("file_id", "animation"),
    }

    attribute, message_type = supported_content_types.get(
        msg.content_type, (None, None)
    )
    if attribute is None:
        await msg.answer("❌ Бот не поддерживает этот формат сообщения")
        return

    content = getattr(msg, message_type, None)
    file_id = (
        content[-1].file_id
        if message_type == "photo"
        else getattr(content, attribute, None)
    )

    await state.update_data(ticket_msg=text)
    await state.update_data(msg_type=message_type)
    await state.update_data(file_id=file_id)

    markup = InlineKeyboardBuilder()

    if not skip_faq:
        for match in best_matches:
            markup.button(text=match[0], url=match[1])

    markup.button(
        text="🛎 Не нашел ответа на свой вопрос. Позвать оператора.",
        callback_data="call_operator",
    )

    markup.adjust(1)
    await msg.answer(
        "По вашему запросу найдены вот такие ответы:", reply_markup=markup.as_markup()
    )


@router.callback_query(F.data == "call_operator")
async def call_operator(query: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    ticket_msg = state_data.get("ticket_msg")
    msg_type = state_data.get("msg_type")
    file_id = state_data.get("file_id")
    if not ticket_msg:
        await query.message.answer("❌ Что-то не так, заполните обращение еще раз")
        return

    # status_ban = await db.get_ban_status(user_id=query.from_user.id)
    # if status_ban == "banned":
    #     await query.message.edit_text("К сожалению, вы были забанены")
    #     return

    ticket_id = await db.create_ticket(
        owner_chat_id=query.from_user.id,
        owner_username=query.from_user.username,
        ticket_detail=ticket_msg,
    )

    ticket_text = f"""
ID-{ticket_id}

Подал: {query.from_user.mention_html()} | ID-{query.from_user.id} | @{query.from_user.username}

▶️ Описание: <b>{encode_html(ticket_msg)}</b>
"""

    if len(ticket_text) > 4096:
        await query.message.answer("❌ Слишком длинное сообщение")
        return

    reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Начать обработку",
                    callback_data="take_ticket",
                )
            ],
        ]
    )

    message_methods = {
        "text": query.bot.send_message,
        "photo": query.bot.send_photo,
        "video": query.bot.send_video,
        "document": query.bot.send_document,
        "audio": query.bot.send_audio,
        "voice": query.bot.send_voice,
        "animation": query.bot.send_animation,
    }

    send_message = message_methods.get(msg_type)
    if send_message is None:
        await query.message.answer("❌ Бот не поддерживает этот формат сообщения")
        return

    if msg_type == "text":
        await message_methods[msg_type](
            CHATS.get("support"), ticket_text, reply_markup=reply_markup
        )
    else:
        logger.debug(file_id)
        await message_methods[msg_type](
            CHATS.get("support"),
            file_id,
            caption=ticket_text,
            reply_markup=reply_markup,
        )

    await query.message.answer(
        """
✅ Ваше обращение передано специалистам. Оператор свяжется с вами в ближайшее время.
    """
    )

    with suppress(TelegramAPIError):
        await query.answer()

    await state.clear()
