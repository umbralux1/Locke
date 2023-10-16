from datetime import datetime

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app import db
from app.keyboards.cancel import cancel_button
from app.keyboards.settings_menu import add_check_buttons

seller_item_amount_text = """
🔽 <b>Введите максимальное кол-во объявлений у продавца</b>

<b>Пример: 5</b>
<b>Пример: 5-10 (Для указания диапазона) </b>
"""

seller_item_sold_amount_text = """
🔽 <b>Введите максимальное кол-во проданных объявлений у продавца</b>

<b>Пример: 5</b>
<b>Пример: 5-10 (Для указания диапазона) </b>
"""

seller_item_bought_amount_text = """
🔽 <b>Введите максимальное кол-во купленных объявлений у продавца</b>

<b>Пример: 5</b>
<b>Пример: 5-10 (Для указания диапазона) </b>
"""

item_has_delivery_text = """🚛 <b>Искать только с доставкой?</b>\n"""

succes_delivery_text = """🚛 <b>Укажите кол-во успешных доставок</b>

<b>Пример: 5</b>
<b>Пример: 5-10 (Для указания диапазона) </b>
"""


save_preset_text = """
💾 <b>Вы хотите сохранить текущие настройки парсера?</b>\n\n <a href='https://telegra.ph/1'>Что такое пресеты и зачем нужны?</a>"""

gender_decline_text = """
🚹 <b>Какой гендер продавцов вам нужен ?</b>"""


item_rating_decline_text = """
⭐️ <b>Вы хотите убрать аккаунты с рейтингом ?</b>\n"""

seller_join_date_text = """
🗓 <b>Укажите дату регистрации продавца</b> 

<b>Пример: 12-11-2015</b>
<b>Пример: 12-11-2015:12-11-2023 (Для указания диапазона) </b>
"""

item_insert_date_text = """
🗓 <b>Укажите дату создания объявления</b>

<b>Пример: 12-11-2015</b>
<b>Пример: 12-11-2015:12-11-2023 (Для указания диапазона) </b>
"""

item_views_text = """
👁 <b>Укажите кол-во просмотров объявления </b>

<b>Пример: 5</b>
<b>Пример: 5-10 (Для указания диапазона) </b>
"""


def get_cleaned_text(text: str) -> str:
    return text.replace(" ⭐", "")


def is_no_filter(text: str) -> bool:
    return text == "Не использовать фильтр"


def is_valid_range(text: str) -> bool:
    if "-" not in text:
        return text.isdigit()

    first_part, last_part = text.split("-", 1)
    if not first_part.isdigit() or not last_part.isdigit():
        return

    if int(first_part) > int(last_part):
        return

    return 0 <= int(last_part) <= 999_999_999


async def check_config_settings(msg, setting_name, filter_name):
    configuration_settings = await db.get_configuration_settings(
        user_id=msg.from_user.id
    )
    if not configuration_settings[0].get(setting_name) and not is_no_filter(
        filter_name
    ):
        cfg_markup = InlineKeyboardBuilder()
        add_check_buttons(
            cfg_markup,
            configuration_settings[0],
            [setting_name],
            ["Включить этот пункт в конфигураторе"],
            [f"update_setting|{setting_name}SUB_MENU"],
        )
        await msg.answer(
            "❌ Вы не можете установить этот фильтр, так как отключен нужный пункт в конфигураторе, если вы хотите использовать этот фильтр включите этот пункт в конфигураторе, либо нажмите не использовать фильтр",
            reply_markup=cfg_markup.as_markup(),
        )
        return

    return True


async def check_price_state(msg: types.Message, state: FSMContext):
    cleaned_text = get_cleaned_text(msg.text)

    if is_no_filter(cleaned_text) or is_valid_range(cleaned_text):
        await state.update_data(item_price_amount=cleaned_text)
        user_data = await state.get_data()
        if not user_data.get("site"):
            await msg.answer("❌ Что-то пошло не так, попробуйте еще раз")
            return

        await db.save_user_keyword(
            user_id=msg.from_user.id,
            keyword=cleaned_text,
            site=user_data.get("site"),
            save_type="item_price_amount",
        )
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )


async def check_seller_item_amount(msg: types.Message, state: FSMContext, ads_type=1):
    async def update_state_based_on_ads_type() -> None:
        update_data = {
            1: {"seller_item_amount": cleaned_text},
            2: {"seller_item_sold_amount": cleaned_text},
            3: {"seller_item_bought_amount": cleaned_text},
        }
        # logger.debug(**update_data.get(ads_type, {}))
        # logger.debug(cleaned_text)
        await state.update_data(**update_data.get(ads_type, {}))

    cleaned_text = get_cleaned_text(msg.text)

    if is_no_filter(cleaned_text) or is_valid_range(cleaned_text):
        if not await check_config_settings(msg, "show_ads_number", cleaned_text):
            return

        await update_state_based_on_ads_type()
        user_data = await state.get_data()
        if not user_data.get("site"):
            await msg.answer("❌ Что-то пошло не так, попробуйте еще раз")
            return

        await db.save_user_keyword(
            user_id=msg.from_user.id,
            keyword=cleaned_text,
            site=user_data.get("site"),
            save_type="seller_item_amount",
        )
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )


def check_date_validity(check_date: str) -> bool:
    if is_no_filter(check_date):
        return True

    date_parts = check_date.split("-")

    if len(date_parts) != 3:
        return

    try:
        day, month, year = map(int, date_parts)

        if not (
            1 <= day <= 31
            and 1 <= month <= 12
            and 1900 <= year <= int(datetime.now().year)
        ):
            return

        datetime.strptime(check_date, "%d-%m-%Y")
        return True
    except ValueError:
        ...


async def generic_date_check(
    msg: types.Message, state: FSMContext, save_type: str, config_key: str
):
    check_date = get_cleaned_text(msg.text)
    user_data = await state.get_data()
    if not user_data.get("site"):
        await msg.answer("❌ Что-то пошло не так, попробуйте еще раз")
        return

    if ":" in check_date:
        start_date, end_date = check_date.split(":", 1)
        if not (check_date_validity(start_date) and check_date_validity(end_date)):
            await msg.answer(
                "❌ Указано неправильно значение, попробуйте еще раз",
                reply_markup=cancel_button,
            )
            return
        if datetime.strptime(end_date, "%d-%m-%Y") < datetime.strptime(
            start_date, "%d-%m-%Y"
        ):
            await msg.answer(
                "❌ Указано неправильно значение, попробуйте еще раз",
                reply_markup=cancel_button,
            )
            return
    elif not check_date_validity(check_date):
        await msg.answer(
            "❌ Указано неправильно значение, попробуйте еще раз",
            reply_markup=cancel_button,
        )
        return

    # Check configuration settings
    if not await check_config_settings(msg, config_key, check_date):
        return

    # Update state and save keyword
    await state.update_data({save_type: check_date})
    await db.save_user_keyword(
        user_id=msg.from_user.id,
        keyword=check_date,
        site=user_data.get("site"),
        save_type=save_type,
    )
    return True


async def check_seller_join_date(msg: types.Message, state: FSMContext):
    return await generic_date_check(
        msg, state, "seller_join_date", "show_person_joined"
    )


async def check_item_insert_date(msg: types.Message, state: FSMContext):
    return await generic_date_check(
        msg, state, "item_insert_date", "show_creation_date"
    )


async def check_item_views_amount(msg: types.Message, state: FSMContext, ads_type=1):
    cleaned_text = get_cleaned_text(msg.text)

    if is_no_filter(cleaned_text) or is_valid_range(cleaned_text):
        if not await check_config_settings(msg, "show_views", cleaned_text):
            return

        await state.update_data(item_views_amount=cleaned_text)
        user_data = await state.get_data()
        if not user_data.get("site"):
            await msg.answer("❌ Что-то пошло не так, попробуйте еще раз")
            return

        await db.save_user_keyword(
            user_id=msg.from_user.id,
            keyword=cleaned_text,
            site=user_data.get("site"),
            save_type="item_views_amount",
        )
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )


async def check_item_rating_delete(msg: types.Message, state: FSMContext):
    cleaned_text = get_cleaned_text(msg.text)

    if cleaned_text in ["Да", "Нет"]:
        if not await check_config_settings(msg, "show_rating", cleaned_text):
            return

        await state.update_data(item_rating_decline=cleaned_text)
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )


async def check_seller_gender(msg: types.Message, state: FSMContext):
    cleaned_text = get_cleaned_text(msg.text)

    if cleaned_text in ["Мужской", "Женский", "Не использовать фильтр"]:
        await state.update_data(seller_gender=cleaned_text)
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )


async def check_item_has_delivery(msg: types.Message, state: FSMContext):
    cleaned_text = get_cleaned_text(msg.text)

    if cleaned_text in [
        "Только с доставкой",
        "Только без доставки",
        "Не использовать фильтр",
    ]:
        if not await check_config_settings(msg, "show_delivery", cleaned_text):
            return

        await state.update_data(item_has_delivery=cleaned_text)
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )


async def check_item_delivery_amount(msg: types.Message, state: FSMContext):
    cleaned_text = get_cleaned_text(msg.text)

    if is_no_filter(cleaned_text) or is_valid_range(cleaned_text):
        if not await check_config_settings(msg, "show_delivery", cleaned_text):
            return

        await state.update_data(item_delivery_amount=cleaned_text)
        user_data = await state.get_data()
        if not user_data.get("site"):
            await msg.answer("❌ Что-то пошло не так, попробуйте еще раз")
            return

        await db.save_user_keyword(
            user_id=msg.from_user.id,
            keyword=cleaned_text,
            site=user_data.get("site"),
            save_type="item_delivery_amount",
        )
        return True

    await msg.answer(
        "❌ Указано неправильно значение, попробуйте еще раз", reply_markup=cancel_button
    )
