from contextlib import suppress

from aiogram import types, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.deep_linking import create_start_link

from app import dp, db, bot
from app.config import REFERRAL_VIDEO, CHATS
from app.filters.channel_check import IsUserInNewsChannel
from app.filters.private_chat import IsPrivate
from app.filters.username import IsUserHasUsername
from app.handlers.site_actions import correct_days_form

router = Router()
dp.include_router(router)

flags = {"throttling_key": "default"}


@dp.message(
    F.text == "🤝 Реферальная программа",
    IsPrivate(),
    IsUserHasUsername(),
    IsUserInNewsChannel(),
    flags=flags,
)
async def referral_handler(msg: types.Message, state: FSMContext):
    await state.set_state(None)

    bot_link = await create_start_link(payload=msg.from_user.id, bot=bot)

    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        video=REFERRAL_VIDEO,
        caption=f"""
<b>▶️ Все просто.</b> Если у Вас есть источник траффика, Вы можете получать бесплатные дни за покупки Ваших рефералов.

<b>▶️ Прибыль:</b>
┣ 3 дня подписки = 1 реферальный день
┣ 7 дней подписки = 3 реферальных дня
┗ 30 дней подписки = 7 реферальных дней

<b>▶️ Как использовать реф. дни:</b>
💼 Начать парсинг
 ┗ Желаемая площадка
    ┗ 🤝 Купить за реферальные дни 

<b>▶️Ссылка</b> для приглашения новых пользователей: <a href="{bot_link}REF">*тык*</a>
┗ Количество приглашенных пользователей: <b>{await db.get_referrals_count(msg.from_user.id)}</b>
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📩 Переслать ссылку для приглашения",
                        switch_inline_query=f"\nМоя реферальная ссылка в Parser\n\n{bot_link}REF",
                    )
                ],
            ]
        ),
    )


async def add_time_to_referral(query, time, chat_id):
    refer_id = await db.get_user_referral_by_id(query.from_user.id)
    time = int(time)
    if refer_id:
        if time < 3:
            return

        bonus_mapping = {
            3: 1,
            7: 2,
            30: 3,
        }

        with suppress(Exception):
            await bot.send_message(
                chat_id=refer_id,
                text=f"🎉 Ваш реферал {query.from_user.mention_html()} купил подписку\n\nВам начислен {bonus_mapping.get(time)} {correct_days_form(bonus_mapping.get(time))}, вы можете купить за них подписку ",
            )

            await query.bot.send_message(
                chat_id=CHATS.get("logs"),
                text=f"#referral\n+{bonus_mapping.get(time)} день пользователю с ID {refer_id} от реферала c ID {chat_id}",
            )

        day_referral = await db.get_user_referral_days(user_id=refer_id)
        await db.set_referral_days(refer_id, day_referral + bonus_mapping.get(time))
