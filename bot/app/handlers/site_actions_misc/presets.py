import asyncio
import re
from contextlib import suppress
from datetime import datetime

import ujson
from aiogram import F, Router, types
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
)
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger

from app import dp, db, bot, redis
from app.config import BANNER_VIDEO, PHONE_SEARCH_ONLY, PHONE_SEARCH_AND_WITHOUT
from app.handlers.start_parsing import run_parser_in_process_pool, check_link_run_stats
from app.keyboards.presets_menu import get_user_presets_buttons, get_preset_actions
from app.keyboards.settings_menu import add_check_buttons
from app.keyboards.site_actions import stop_parser
from app.keyboards.tokens import token_buttons
from app.misc.parser_essintials import get_parser_status
from app.sites_config import sites

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("presets"))
async def presets(query: CallbackQuery):
    site = query.data.split("|")[-1]

    user_presets = await db.get_presets(query.from_user.id, site)
    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption="🔽 Выберите нужный вам пресет\n\n <a href='https://telegra.ph/1'>Что такое пресеты и зачем нужны?</a>",
            reply_markup=get_user_presets_buttons(site=site, user_presets=user_presets),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_prsts_confirm"))
async def delete_presets_all_confirm(query: CallbackQuery):
    site = query.data.split("|")[-1]
    # logger.debug(site)

    await db.delete_all_user_presets(query.from_user.id, site)

    user_presets = await db.get_presets(query.from_user.id, site)
    with suppress(TelegramAPIError):
        await query.bot.send_video(
            video=BANNER_VIDEO,
            chat_id=query.from_user.id,
            caption="🔽 Выберите нужный вам пресет\n\n <a href='https://telegra.ph/1'>Что такое пресеты и зачем нужны?</a>",
            reply_markup=get_user_presets_buttons(site=site, user_presets=user_presets),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_prsts_all"))
async def delete_presets_all(query: CallbackQuery):
    site = query.data.split("|")[-1]
    # logger.debug(site)

    await query.message.answer(
        "Вы точно хотите удалить все ваши пресеты?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data=f"delete_prsts_confirm|{site}",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_cprsts_confirm"))
async def delete_preset_confirm(query: CallbackQuery):
    site = query.data.split("|")[-2]
    text_title = query.data.split("|")[-1]

    await db.delete_user_preset_by_title(query.from_user.id, site, text_title)

    user_presets = await db.get_presets(query.from_user.id, site)
    with suppress(TelegramAPIError):
        await query.bot.send_video(
            video=BANNER_VIDEO,
            chat_id=query.from_user.id,
            caption="🔽 Выберите нужный вам пресет\n\n <a href='https://telegra.ph/1'>Что такое пресеты и зачем нужны?</a>",
            reply_markup=get_user_presets_buttons(site=site, user_presets=user_presets),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("delete_prsts"))
async def delete_preset(query: CallbackQuery):
    site = query.data.split("|")[-2]
    text_title = query.data.split("|")[-1]

    await query.message.answer(
        "Вы точно хотите удалить этот пресет?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да",
                        callback_data=f"delete_cprsts_confirm|{site}|{text_title}",
                    )
                ]
            ]
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


def humanize_title_preset(text):
    mapping = {
        "link_or_name": "🔍 Поиск по",
        "item_price_amount": "💰 Цена",
        "seller_item_amount": "📂 Кол-во объявлений продавца",
        "seller_join_date": "🗓 Дата регистрации продавца",
        "item_insert_date": "🗓 Дата создания товара",
        "item_views_amount": "👁 Кол-во просмотров товара",
        "item_rating_decline": "⭐️ Исключать аккаунты с рейтингом",
        "item_delivery_amount": "🚛 Кол-во успешных доставок",
        "seller_gender": "🚹 Гендер продавца",
        "seller_item_bought_amount": "📂 Кол-во купленных товаров у  продавца",
        "seller_item_sold_amount": "📂 Кол-во проданных товаров у  продавца",
        "item_has_delivery": "🚛 Искать только с доставкой",
    }
    return mapping.get(text, text)


@router.callback_query(F.data.contains("show_prst"))
async def show_presets(query: CallbackQuery, state: FSMContext):
    _, site, text_title = query.data.split("|")

    if site == "last_parser":
        user_text = await db.get_user_last_parser(
            user_id=query.from_user.id,
        )
        if not user_text:
            await query.message.answer("❌ У вас нет последних парсингов")
            return
    else:
        user_text = await db.get_user_presets_by_title(
            site=site,
            user_id=query.from_user.id,
            text_title=text_title,
        )

    share_id = user_text[0].get("share_id")
    user_text = ujson.loads(user_text[0].get("text_body"))

    items_to_ignore = ["parser_mode", "site"]
    text = "\n".join(
        f"{humanize_title_preset(key)}: <b>{value[:700] if key == 'link_or_name' else value}</b>"
        for key, value in user_text.items()
        if key not in items_to_ignore
        and value
        and value not in ["Нет", "Не использовать фильтр"]
    )

    try:
        configuration_settings = await db.get_configuration_settings(
            user_id=query.from_user.id
        )
        configuration_settings = configuration_settings[0]
    except IndexError:
        await query.message.answer("❌ Пропишите /start и попробуй заново")
        return

    # logger.debug(user_text)
    site_ = user_text.get("site") if site == "last_parser" else site
    if configuration_settings.get("blacklist_type") == 2:
        await check_link_run_stats(
            user_text.get("link_or_name"),
            site_,
            query,
            configuration_settings,
            state,
        )

    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption=f"""
⚙️ Настройки вашего пресета:

{text}
            """,
            reply_markup=await get_preset_actions(site, text_title, share_id, bot),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("change_to_current_date"))
async def change_to_current_date(
    query: CallbackQuery,
    state: FSMContext,
):
    text_title = query.data.split("|")[-1]
    site = query.data.split("|")[-2]
    orig_site = query.data.split("|")[-2]

    if site == "last_parser":
        user_text = await db.get_user_last_parser(user_id=query.from_user.id)
        user_text = ujson.loads(user_text[0].get("text_body"))
        text_title = "last_parser"
        site = user_text.get("site")
    else:
        user_text = await db.get_user_presets_by_title(
            site=site,
            user_id=query.from_user.id,
            text_title=text_title,
        )
        user_text = user_text[0]
        user_text = ujson.loads(user_text.get("text_body"))

    share_id = user_text.get("share_id")
    user_text["item_insert_date"] = datetime.now().strftime("%d-%m-%Y")

    await db.set_new_preset_body(
        query.from_user.id, site, text_title, str(ujson.dumps(user_text))
    )

    items_to_ignore = ["parser_mode", "site"]
    text = "\n".join(
        f"{humanize_title_preset(key)}: <b>{value}</b>"
        for key, value in user_text.items()
        if key not in items_to_ignore
        and value
        and value not in ["Нет", "Не использовать фильтр"]
    )

    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            caption=f"""
⚙️ Настройки вашего пресета:

{text}""",
            reply_markup=await get_preset_actions(orig_site, text_title, share_id, bot),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("run_parser_preset"))
async def run_parser_from_preset(
    query: CallbackQuery,
    state: FSMContext,
):
    def build_cfg_markup():
        cfg_markup = InlineKeyboardBuilder()
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            [config_name],
            ["Включить этот пункт в конфигураторе"],
            [f"update_setting|{config_name}"],
        )

        return cfg_markup.as_markup()

    site, text_title = query.data.split("|")[-2:]
    status = await get_parser_status(query.from_user.id, redis)
    if status == "running":
        await query.message.answer(
            "❌ Нельзя парсить одновременно 2 площадки", reply_markup=stop_parser
        )
        return

    if "WATCH" in site:
        site = site.replace("WATCH", "")
        await state.update_data(watch_parser=True)
    else:
        await state.update_data(watch_parser=False)

    if site == "last_parser":
        user_text = await db.get_user_last_parser(user_id=query.from_user.id)
    else:
        user_text = await db.get_user_presets_by_title(
            site=site,
            user_id=query.from_user.id,
            text_title=text_title,
        )

    user_text = ujson.loads(user_text[0].get("text_body"))
    state_config = {
        "seller_item_sold_amount": "show_ads_number",
        "seller_item_bought_amount": "show_ads_number",
        "seller_item_amount": "show_ads_number",
        "seller_join_date": "show_person_joined",
        "item_insert_date": "show_creation_date",
        "item_views_amount": "show_views",
        "item_rating_decline": "show_rating",
        "item_delivery_amount": "show_delivery",
        "item_has_delivery": "show_delivery",
    }

    expiry_date = await db.get_user_subscription_site(
        site=user_text["site"], user_id=query.from_user.id
    )
    if not expiry_date or expiry_date and expiry_date < datetime.now():
        await query.bot.send_video(
            chat_id=query.from_user.id,
            video=BANNER_VIDEO,
            caption="⚠️ У вас кончилась подписка",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💰 Продлить подписку",
                            callback_data=f"renew_subscription|{user_text['site']}",
                        ),
                    ],
                ]
            ),
        )
        return

    configuration_settings = await db.get_configuration_settings(
        user_id=query.from_user.id
    )
    if configuration_settings is None:
        await query.message.answer("❌ Пропишите /start и попробуй заново")
        return

    configuration_settings = configuration_settings[0]

    for state_name, state_value in user_text.items():
        config_name = state_config.get(state_name)
        if (
            config_name
            and state_value
            not in [
                "Не использовать фильтр",
                "Нет",
                "parser_mode",
                "seller_gender",
                "item_price_amount",
                "link_or_name",
                "site",
                "",
            ]
            and not configuration_settings.get(config_name)
        ):
            await state.update_data(update_button_from_search=True)
            await state.update_data(
                text_to_update=[f"Включить этот пункт в конфигураторе%{config_name}"]
            )

            await query.message.answer(
                "❌ Вы не можете запустить этот пресет, так как отключен пункт в конфигураторе, если вы хотите "
                "использовать этот пресет включите этот пункт в конфигураторе",
                reply_markup=build_cfg_markup(),
            )
            return
        await state.update_data(**{state_name: state_value})

    with suppress(TelegramAPIError):
        await query.answer()

    with suppress(TelegramAPIError):
        await query.message.delete()

    if sites[user_text["site"]].get("need_tokens") and configuration_settings.get(
        "phone_search_type"
    ) in [PHONE_SEARCH_ONLY, PHONE_SEARCH_AND_WITHOUT]:
        await query.message.answer(
            """
▶️ <b>Введите ваши токены для получения номеров телефона</b>

<a href='https://telegra.ph/1'>Как парсить без токена?</a>

<i>▶️ Мануал по получению токена:</i> https://telegra.ph/1

<i>▶️ Пример ввода токенов:</i>
0bf09bdf0b940934059430409vfd
0bf09bdf0b940934059430409vfd
            """,
            reply_markup=token_buttons,
        )
        await state.set_state("get_token_for_preset")
        return

    # await run_parser_in_process_pool(query.message, state)
    asyncio.create_task(run_parser_in_process_pool(query.message, state))


@dp.message(StateFilter("get_token_for_preset"))
async def get_token_for_preset(msg: types.Message, state: FSMContext):
    pick = msg.text

    state_date = await state.get_data()
    site = state_date.get("site")

    if pick == "⏮ Вставить свои токены из последнего запуска":
        tokens = await db.get_user_tokens(msg.from_user.id, site)
        if not tokens:
            await msg.answer("❌ У вас нету сохраненных токенов")
            return

        if re.search("[а-яА-Я]", tokens):
            await msg.answer("❌ В токене не может быть кириллицы")
            return

        await state.update_data(tokens=tokens.replace(";", "\n\n"))
    else:
        if re.search("[а-яА-Я]", pick):
            await msg.answer("❌ В токене не может быть кириллицы")
            return
        await state.update_data(tokens=pick)

    await state.set_state(None)
    asyncio.create_task(run_parser_in_process_pool(msg, state))
