from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app import db, bot
from app.misc.msg_templates_manipulator import (
    get_visibility_setting_menu_param,
)


def get_configuration_str_for_share(configuration_settings):
    filtered_dict = {
        k: v
        for k, v in configuration_settings.items()
        if k not in ["user_id", "getter_ads_limit"]
    }
    converted_dict = {
        k: (1 if v else 0) if isinstance(v, bool) else v
        for k, v in filtered_dict.items()
    }
    return "".join(map(str, converted_dict.values()))


def determine_text_by_phone_search_type(configuration_settings):
    phone_search_type = configuration_settings.get("phone_search_type")
    phone_search_type_text = "✅ Только с номерами [1/4]"
    if phone_search_type == 1:
        phone_search_type_text = "Только с номерами и без номеров [2/4]"
    elif phone_search_type == 2:
        phone_search_type_text = "Только без номеров [3/4]"
    elif phone_search_type == 3:
        phone_search_type_text = "Смотреть номера самому [4/4]"

    return phone_search_type_text


def determine_text_by_blacklist_type(configuration_settings):
    blacklist_type = configuration_settings.get("blacklist_type")
    blacklist_type_text = "❌ Искать только непросмотренные объявления [1/3]"
    if blacklist_type == 1:
        blacklist_type_text = f"{blacklist_type_text.replace('[1/3]', '')} [2/3]"
    elif blacklist_type == 2:
        blacklist_type_text = "Общий черный список [3/3]"

    return blacklist_type_text


def determine_text_by_style(configuration_settings):
    style_type = configuration_settings.get("style")
    style_type_text = "Стиль: Стандартный [1/3]"
    if style_type == 1:
        style_type_text = "Стиль: Минималистичный [2/3]"
    elif style_type == 2:
        style_type_text = "Стиль: Легенда [3/3]"
    # elif style_type == 3:
    #     style_type_text = "Стиль: Глиномес [4/2]"

    return style_type_text


def add_button(cfg_markup, text_or_buttons, callback_data=None, new_row=False):
    if isinstance(text_or_buttons, str) and callback_data is not None:
        button = InlineKeyboardButton(text=text_or_buttons, callback_data=callback_data)
        if new_row:
            cfg_markup.row(button)
        else:
            cfg_markup.button(
                text=button.text,
                callback_data=button.callback_data,
            )
    elif isinstance(text_or_buttons, list):
        cfg_markup.row(
            *[
                InlineKeyboardButton(text=text, callback_data=callback_data)
                for text, callback_data in text_or_buttons
            ]
        )


def add_check_buttons(
    cfg_markup, configuration_settings, setting_keys, texts, callback_datas
):
    buttons = []
    for setting_key, text, callback_data in zip(setting_keys, texts, callback_datas):
        setting_value = configuration_settings.get(setting_key)
        check_text = text
        if setting_value:
            check_text = f"✅ {check_text.replace('❌', '')}"
        buttons.append((check_text, f"{callback_data}|{setting_value}"))
    add_button(cfg_markup, buttons)


async def get_settings_btns(msg, user_id) -> InlineKeyboardMarkup:
    cfg_markup = InlineKeyboardBuilder()

    state_data = await get_visibility_setting_menu_param(user_id)

    show_log_view = state_data.get("show_log_view")
    show_filtration_exclude = state_data.get("show_filtration_exclude")

    try:
        configuration_settings = await db.get_configuration_settings(user_id=user_id)
        configuration_settings = configuration_settings[0]
    except IndexError:
        await db.init_user_settings(user_id=user_id)
        configuration_settings = await db.get_configuration_settings(user_id=user_id)
        configuration_settings = configuration_settings[0]

    if show_log_view:
        add_button(
            cfg_markup,
            "Отображение лога 🔼",
            "settings_toggle|hide_log_view",
            new_row=True,
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["show_photo", "show_title"],
            ["Фото", "Название"],
            ["update_setting|show_photo", "update_setting|show_title"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["show_price", "show_location"],
            ["Цена", "Местоположение"],
            ["update_setting|show_price", "update_setting|show_location"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["show_desc", "show_views"],
            ["Описание", "Просмотры"],
            ["update_setting|show_desc", "update_setting|show_views"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["show_creation_date", "show_delivery"],
            ["Дата создания", "Доставка"],
            ["update_setting|show_creation_date", "update_setting|show_delivery"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["show_person_name", "show_rating"],
            ["Имя", "Рейтинг"],
            ["update_setting|show_person_name", "update_setting|show_rating"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["show_ads_number", "show_person_joined"],
            ["Кол-во объявлений", "Дата регистрации"],
            ["update_setting|show_ads_number", "update_setting|show_person_joined"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["compact_view"],
            ["Компактный лог"],
            ["update_setting|compact_view"],
        )

        style_text = determine_text_by_style(configuration_settings)
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["style"],
            [style_text],
            ["update_setting|style"],
        )

        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["old_msg_send"],
            ["Отправлять сообщения сразу после нахождения"],
            ["update_setting|old_msg_send"],
        )
    else:
        add_button(
            cfg_markup,
            "Отображение лога 🔽",
            "settings_toggle|show_log_view",
            new_row=True,
        )

    if show_filtration_exclude:
        add_button(
            cfg_markup,
            "Фильтрация и исключения 🔼",
            "settings_toggle|hide_filtration_exclude",
            new_row=True,
        )

        blacklist_type_text = determine_text_by_blacklist_type(configuration_settings)
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["blacklist_type"],
            [blacklist_type_text],
            ["update_setting|blacklist_type"],
        )

        phone_search_type_text = determine_text_by_phone_search_type(
            configuration_settings
        )

        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["only_person_wa"],
            ["Только с whatsapp"],
            ["update_setting|only_person_wa"],
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["phone_search_type"],
            [phone_search_type_text],
            ["update_setting|phone_search_type"],
        )
        add_button(
            cfg_markup,
            [
                ("🗣️🚫 Фильтрация слов", "blacklist_words"),
                ("📑🚫 Фильтрация объявлений", "blacklist_ads"),
            ],
        )
        add_button(
            cfg_markup, [("🎯 Кол-во объявлений для выдачи", "set_getter_ads_limit")]
        )
    else:
        add_button(
            cfg_markup,
            "Фильтрация и исключения 🔽",
            "settings_toggle|show_filtration_exclude",
            new_row=True,
        )

    cfg_markup.row(
        InlineKeyboardButton(
            text="📎 Поделиться своим конфигуратором",
            switch_inline_query=f"\n\n🛠 Мои настройки конфигуратора\n{await create_start_link(payload=get_configuration_str_for_share(configuration_settings), bot=bot)}CFG",
        )
    )

    cfg_markup.row(
        InlineKeyboardButton(text="🔄 Сброс настроек", callback_data="settings_reset"),
        InlineKeyboardButton(text="🔍 Поиск", callback_data="settings_search"),
    )

    return cfg_markup.as_markup()
