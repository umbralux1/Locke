from contextlib import suppress

import ujson
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app import redis, db, dp
from app.keyboards.blacklist_ads_menu import get_blacklist_ads_btns
from app.keyboards.settings_menu import (
    get_settings_btns,
    add_check_buttons,
    determine_text_by_phone_search_type,
    determine_text_by_blacklist_type,
    determine_text_by_style,
)
from app.misc.msg_templates_manipulator import (
    manipulate_msg_template,
    get_visibility_setting_menu_param,
)

SETTING_RESPONSES = {
    "only_person_wa": {
        "False": "Теперь вы будете получать только тех продавцов, которые есть в whatsapp"
    },
    "blacklist_type": {
        "0": "Теперь вы будете получать только непросмотренные объявления, но учтите, что это не общий черный список, он может выдать объявления от продавца, с которым уже работали",
        "1": "Теперь вы будете получать только уникальные объявления, от продавцов с которыми не работали, но есть нюанс, другие пользователи могут тоже увидеть ваше объявление если у них полностью отключен чс",
    },
    "phone_search_type": {
        "0": "Теперь вы будете получать объявления независимо от того есть ли у них номер телефона или нет",
        "1": "Теперь вы будете получать объявления только где нет номеров телефона",
        "2": "Теперь вы будете получать объявления, где есть номер телефона, но посмотреть его можно только на сайте",
    },
    "style": {
        "0": "Минималистичный",
        "2": "Стандартный",
        "1": "Легенда",
    },
}

BLACKLIST_TYPE_MAX_VALUE = 3
PHONE_SEARCH_TYPE_MAX_VALUE = 4
STYLE_MAX_VALUE = 3

router = Router()
dp.include_router(router)


def determine_setting_value(setting_name, setting_value_str):
    sub_menu = "SUB_MENU" in setting_name
    if sub_menu:
        setting_name = setting_name.replace("SUB_MENU", "")
        sub_menu = True

    if setting_name == "blacklist_type":
        setting_value = (int(setting_value_str) + 1) % BLACKLIST_TYPE_MAX_VALUE
    elif setting_name == "phone_search_type":
        setting_value = (int(setting_value_str) + 1) % PHONE_SEARCH_TYPE_MAX_VALUE
    elif setting_name == "style":
        setting_value = (int(setting_value_str) + 1) % STYLE_MAX_VALUE
    else:
        setting_value = setting_value_str == "False"

    # logger.debug(setting_value)
    return setting_name, setting_value, sub_menu


@router.callback_query(F.data.contains("update_setting"))
async def update_setting(query: CallbackQuery, state: FSMContext):
    _, setting_name, setting_value_str = query.data.split("|")
    state_data = await state.get_data()

    setting_name, setting_value, sub_menu = determine_setting_value(
        setting_name, setting_value_str
    )

    await db.update_user_setting(query.from_user.id, setting_name, setting_value)

    # logger.debug(setting_value_str)
    response_text = SETTING_RESPONSES.get(setting_name, {}).get(setting_value_str)
    if response_text:
        with suppress(TelegramBadRequest):
            await query.answer(response_text, show_alert=True)

    with suppress(TelegramBadRequest):
        await query.answer()

    if state_data.get("update_button_from_search"):
        text_to_update = state_data.get("text_to_update")
        if text_to_update:
            configuration_settings = await db.get_configuration_settings(
                user_id=query.from_user.id
            )
            configuration_settings = configuration_settings[0]
            cfg_markup = InlineKeyboardBuilder()
            for el in text_to_update:
                try:
                    button_name, callback = el.split("%")
                    if "phone_search_type" in callback:
                        button_name = determine_text_by_phone_search_type(
                            configuration_settings
                        )
                    elif "blacklist_type" in callback:
                        button_name = determine_text_by_blacklist_type(
                            configuration_settings
                        )
                    elif "style" in callback:
                        button_name = determine_text_by_style(configuration_settings)

                    add_check_buttons(
                        cfg_markup,
                        configuration_settings,
                        [callback.replace("update_setting|", "")],
                        [button_name],
                        [callback],
                    )
                except ValueError:
                    logger.debug("need two elements")
            await query.message.edit_reply_markup(
                reply_markup=cfg_markup.as_markup(),
            )
            return

    if sub_menu:
        markup = await get_blacklist_ads_btns(query.from_user.id)
    else:
        markup = await get_settings_btns(query.message, query.from_user.id)

    state_data = await get_visibility_setting_menu_param(query.from_user.id)
    if state_data.get("show_log_view"):
        with suppress(TelegramAPIError):
            if query.message.caption is not None:
                await query.message.edit_caption(
                    caption=await manipulate_msg_template(user_id=query.from_user.id),
                    reply_markup=markup,
                )
    elif (
        query.message.caption is not None
        and "Здесь вы можете настроить какие данные вы хотите видеть, а ка"
        not in query.message.caption
    ):
        with suppress(TelegramAPIError):
            await query.message.edit_caption(
                caption="▶️ Здесь вы можете настроить какие данные вы хотите видеть, а какие вам не нужны\n\n▶️ Чем меньше галочек здесь будет, тем быстрее будет парсить, оставьте только то, что вам необходимо\n\n▶️ Нажмите на нужный вам пункт, чтобы закрыть/расскрыть настройки",
                reply_markup=markup,
            )
    else:
        with suppress(TelegramAPIError):
            await query.message.edit_reply_markup(reply_markup=markup)


@router.callback_query(F.data.contains("settings_toggle|"))
async def toggle_setting(query: CallbackQuery):
    hide_or_show = query.data.split("|")[-1].split("_")[0]
    hide_or_show = hide_or_show != "hide"
    action = query.data.split("|")[-1].replace("hide", "show")

    await redis.hset(
        f"user_settings:{query.from_user.id}",
        action,
        ujson.dumps(hide_or_show),
    )

    state_data = await get_visibility_setting_menu_param(query.from_user.id)
    if state_data.get("show_log_view"):
        with suppress(TelegramAPIError):
            if query.message.caption is not None:
                try:
                    await query.message.edit_caption(
                        caption=await manipulate_msg_template(
                            user_id=query.from_user.id
                        ),
                        reply_markup=await get_settings_btns(
                            query.message, query.from_user.id
                        ),
                    )
                except IndexError:
                    await query.message.answer("❌ Пропишите /start и попробуй заново")
                    return
    elif (
        query.message.caption is not None
        and "Здесь вы можете настроить какие данные вы хотите видеть, а ка"
        not in query.message.caption
    ):
        with suppress(TelegramAPIError):
            await query.message.edit_caption(
                caption="▶️ Здесь вы можете настроить какие данные вы хотите видеть, а какие вам не нужны\n\n▶️ Чем меньше галочек здесь будет, тем быстрее будет парсить, оставьте только то, что вам необходимо\n\n▶️ Нажмите на нужный вам пункт, чтобы закрыть/расскрыть настройки",
                reply_markup=await get_settings_btns(query.message, query.from_user.id),
            )
    else:
        with suppress(TelegramAPIError):
            await query.message.edit_reply_markup(
                reply_markup=await get_settings_btns(query.message, query.from_user.id)
            )

    with suppress(TelegramAPIError):
        await query.answer()
