from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import db
from app.keyboards.settings_menu import add_check_buttons, add_button


async def get_blacklist_ads_btns(user_id):
    cfg_markup = InlineKeyboardBuilder()

    configuration_settings = await db.get_configuration_settings(user_id=user_id)
    configuration_settings = configuration_settings[0]

    add_check_buttons(
        cfg_markup,
        configuration_settings,
        ["exclude_cars"],
        ["Исключать машины"],
        ["update_setting|exclude_carsSUB_MENU"],
    )
    add_check_buttons(
        cfg_markup,
        configuration_settings,
        ["exclude_estate"],
        ["Исключать недвижимость"],
        ["update_setting|exclude_estateSUB_MENU"],
    )
    add_check_buttons(
        cfg_markup,
        configuration_settings,
        ["exclude_animals"],
        ["Исключать животных"],
        ["update_setting|exclude_animalsSUB_MENU"],
    )
    add_check_buttons(
        cfg_markup,
        configuration_settings,
        ["exclude_services"],
        ["Исключать услуги"],
        ["update_setting|exclude_servicesSUB_MENU"],
    )
    add_check_buttons(
        cfg_markup,
        configuration_settings,
        ["exclude_digital_products"],
        ["Исключать цифровые товары (карточки пополнения, промокоды, аккаунты)"],
        ["update_setting|exclude_digital_productsSUB_MENU"],
    )
    add_button(cfg_markup, "◀", "return_to_settings")

    cfg_markup.adjust(1)
    return cfg_markup.as_markup()
