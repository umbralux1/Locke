import asyncio
from contextlib import suppress

from aiogram import types, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
)
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from fuzzywuzzy import fuzz

from app import dp, db
from app.config import BANNER_VIDEO
from app.filters.channel_check import IsUserInNewsChannel
from app.filters.private_chat import IsPrivate
from app.filters.username import IsUserHasUsername
from app.keyboards.cancel import cancel_button
from app.keyboards.settings_menu import (
    get_settings_btns,
    determine_text_by_blacklist_type,
    add_check_buttons,
    determine_text_by_phone_search_type,
    determine_text_by_style,
)
from app.misc.msg_templates_manipulator import (
    manipulate_msg_template,
    get_visibility_setting_menu_param,
)
from app.misc.parser_essintials import pool_process

router = Router()
dp.include_router(router)

flags = {"throttling_key": "default"}


@dp.message(
    F.text == "⚙️ Настройки",
    IsPrivate(),
    IsUserHasUsername(),
    IsUserInNewsChannel(),
    flags=flags,
)
async def settings_handler(msg: types.Message, state: FSMContext):
    await state.set_state(None)

    state_data = await get_visibility_setting_menu_param(msg.from_user.id)
    if state_data.get("show_log_view"):
        text = await manipulate_msg_template(user_id=msg.from_user.id)
    else:
        text = "▶️ Здесь вы можете настроить какие данные вы хотите видеть, а какие вам не нужны\n\n▶️ Чем меньше галочек здесь будет, тем быстрее будет парсить, оставьте только то, что вам необходимо\n\n▶️ Нажмите на нужный вам пункт, чтобы закрыть/расскрыть настройки"

    await state.update_data(update_button_from_search=False)
    await msg.bot.send_video(
        chat_id=msg.from_user.id,
        caption=text,
        reply_markup=await get_settings_btns(msg, msg.from_user.id),
        video=BANNER_VIDEO,
    )


def find_best_matches_fuzzy(user_query, settings_buttons_name, top_n=5):
    matches = {
        name: (fuzz.ratio(user_query.lower(), name.lower()), callback)
        for name, callback in settings_buttons_name.items()
    }
    sorted_matches = sorted(matches.items(), key=lambda item: -item[1][0])

    # Modify the return format to include the callback.
    result = [(name, match[1]) for name, match in sorted_matches]

    return result[:top_n]


async def find_best_matches_fuzzy_async(user_query, settings_buttons_name, top_n=5):
    return find_best_matches_fuzzy(user_query, settings_buttons_name, top_n)
    # return await asyncio.get_event_loop().run_in_executor(
    #     pool_process, find_best_matches_fuzzy, user_query, settings_buttons_name, top_n
    # )


@router.callback_query(F.data == "settings_search")
async def settings_search(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="🔧 Введите настройку для поиска", reply_markup=cancel_button
        )

    await state.set_state("settings_search")

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("settings_search"))
async def settings_search(msg: types.Message, state: FSMContext):
    user_id = msg.from_user.id

    if len(msg.text) > 4096:
        await msg.answer("❌ Слишком много символов")
        return

    configuration_settings = await db.get_configuration_settings(user_id=user_id)
    configuration_settings = configuration_settings[0]

    blacklist_type_text = determine_text_by_blacklist_type(configuration_settings)
    phone_search_type_text = determine_text_by_phone_search_type(configuration_settings)
    style_type_text = determine_text_by_style(configuration_settings)

    settings_buttons_name = {
        "Фото": "update_setting|show_photo",
        "Название": "update_setting|show_title",
        "Цена": "update_setting|show_price",
        "Местоположение": "update_setting|show_location",
        "Описание": "update_setting|show_desc",
        "Просмотры": "update_setting|show_views",
        "Дата создания": "update_setting|show_creation_date",
        "Доставка": "update_setting|show_delivery",
        "Имя": "update_setting|show_person_name",
        "Рейтинг": "update_setting|show_rating",
        "Кол-во объявлений": "update_setting|show_ads_number",
        "Дата регистрации": "update_setting|show_person_joined",
        "Компактный лог": "update_setting|compact_view",
        blacklist_type_text: "update_setting|blacklist_type",
        "Только с whatsapp": "update_setting|only_person_wa",
        phone_search_type_text: "update_setting|phone_search_type",
        style_type_text: "update_setting|style",
    }

    result = await find_best_matches_fuzzy_async(
        msg.text, settings_buttons_name, top_n=3
    )

    text_to_update = []
    cfg_markup = InlineKeyboardBuilder()
    for button_name, callback in result:
        text_to_update.append(f"{button_name}%{callback}")
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            [callback.replace("update_setting|", "")],
            [button_name],
            [callback],
        )

    await state.update_data(update_button_from_search=True)
    await state.update_data(text_to_update=text_to_update)
    # logger.debug(text_to_update)
    await msg.answer("🔍 Результаты поиска:", reply_markup=cfg_markup.as_markup())


@router.callback_query(F.data == "settings_reset")
async def settings_reset(query: CallbackQuery):
    await query.message.answer(
        "Вы точно хотите сбросить все настройки?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data="settings_reset_confirm",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "settings_reset_confirm")
async def settings_reset_confirm(query: CallbackQuery, state: FSMContext):
    await db.reset_user_settings(query.from_user.id)
    await query.message.answer("✅ Настройки сброшены")

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "return_to_settings")
async def return_to_settings(query: CallbackQuery, state: FSMContext):
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption="▶️ Здесь вы можете настроить какие данные вы хотите видеть, а какие вам не нужны\n\n▶️ Чем меньше галочек здесь будет, тем быстрее будет парсить, оставьте только то, что вам необходимо\n\n▶️ Нажмите на нужный вам пункт, чтобы закрыть/расскрыть настройки",
            reply_markup=await get_settings_btns(query.message, query.from_user.id),
        )

    with suppress(TelegramAPIError):
        await query.answer()
