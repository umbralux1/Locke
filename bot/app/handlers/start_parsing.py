import asyncio
import traceback
from contextlib import suppress
from datetime import datetime
from io import BytesIO
from time import perf_counter
from urllib.parse import unquote

import aiohttp
import ujson
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import ClientTimeout, TCPConnector
from loguru import logger
from redis.asyncio import ConnectionPool, Redis

from app import dp, db, redis, worker
from app import redis as redis_
from app.config import (
    LIMIT_MAX_LINKS,
    LIMIT_MAX_PRESET_NAME_LENGTH,
    LIMIT_MAX_PRESETS,
    ITEMS_POOL,
    URLS_POOL,
    LIMIT_ADS_MAX,
    REDIS_HOST,
    REDIS_PORT,
    MAX_TOKEN,
    TOKEN_ERRORS,
    REDIS_PASS,
    USER_MUTEX,
)
from app.handlers.site_actions_misc.custom_text import validation_user_text
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.cancel import cancel_button, stop_button
from app.keyboards.memorable_filters import get_price_parser_btns
from app.keyboards.settings_menu import add_check_buttons
from app.keyboards.site_actions import (
    get_saved_user_links,
    get_result_btns,
    stop_parser,
    stop_parser_json,
)
from app.keyboards.start_menu_markup import get_start_menu_markup
from app.misc.avg_calculation import (
    get_avg_values_by_period,
    generate_avg_text,
)
from app.misc.notify import send_text, send_document
from app.misc.parser_essintials import (
    get_parser_status,
    error_code_mapping,
    pool_process,
    wrapper_for_run_cpu_bound,
    handle_ticker,
)
from app.misc.parser_logger import log_parser_run_for_admin
from app.misc.parser_pools_executors import get_url_by_place, pool_watcher, get_items
from app.misc.time_declension import humanize_date
from app.sites_config import sites

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("start_parser"))
async def start_parsing(query: CallbackQuery, state: FSMContext):
    parser_type = query.data.split("|")[-2]
    site = query.data.split("|")[-1]

    if parser_type == "backgrnd":
        await state.update_data(watch_parser=True)
    else:
        await state.update_data(watch_parser=False)

    status = await get_parser_status(query.from_user.id, redis)
    if status == "running":
        await query.message.answer(
            "❌ Нельзя парсить одновременно 2 площадки", reply_markup=stop_parser
        )
        return

    with suppress(TelegramAPIError):
        await query.message.edit_caption(
            caption=f"<b>💡 Введите ссылки на категории или ключевые слова[Max: {LIMIT_MAX_LINKS}]</b>\n\n<b>Пример ссылки: "
                    f"{sites.get(site).get('link_example')}</b>\n\n",
            reply_markup=await get_saved_user_links(site, query.from_user.id),
        )

    await state.update_data(site=site)
    await state.set_state("set_keyword_parser")

    with suppress(TelegramAPIError):
        await query.answer()


def has_duplicates(text):
    lines = text.strip().split("\n")

    unique_lines = set()

    for line in lines:
        if line.casefold() in unique_lines:
            return
        unique_lines.add(line.casefold())

    return True


async def set_state_by_site(site: str, state):
    await state.set_state(sites.get(site).get("init_state"))


@router.message(StateFilter("set_keyword_parser"))
async def set_keyword_parser(msg: Message, state: FSMContext):
    msg = msg.message if isinstance(msg, CallbackQuery) else msg

    state_date = await state.get_data()
    row_id = state_date.get("row_id")
    save_link = True
    if row_id:
        save_link = False
        text = await db.get_saved_user_links_by_id(row_id=int(row_id))
    else:
        text = msg.text

    parser_mode = "1" if "https://" in text or "http://" in text else "2"
    await state.update_data(parser_mode=parser_mode)
    await state.update_data(row_id="")

    user_data = await state.get_data()
    site = user_data.get("site")
    links = text

    if len(links.split("\n")) > LIMIT_MAX_LINKS:
        await msg.answer(f"❌ Вы не можете указать больше {LIMIT_MAX_LINKS} ссылок/слов")
        return

    if not has_duplicates(links):
        await msg.answer("❌ Ссылки/Cлова должны быть разные")
        return

    try:
        if parser_mode == "1" and sites.get(site).get("link_signature") not in links:
            await msg.answer(
                "❌ Указанная ссылка не валидна, попробуйте еще раз",
                reply_markup=cancel_button,
            )
            return

        if sites.get(site).get("link_signature") in links and parser_mode == "2":
            await msg.answer(
                "❌ Указанная ссылка не валидна, попробуйте еще раз",
                reply_markup=cancel_button,
            )
            return
    except AttributeError:
        await msg.answer("❌ Что-то пошло не так, попробуйте заново")
        return

    unquote_links = unquote(links)

    if (
            "@" in unquote_links
            or "{" in unquote_links
            or "'" in unquote_links
            or "$" in unquote_links
            or ";" in unquote_links
    ):
        await msg.answer(
            "❌ Указанная ссылка не валидна, попробуйте еще раз",
            reply_markup=cancel_button,
        )
        return

    if save_link:
        await db.save_user_link(msg.chat.id, site, links)

    try:
        configuration_settings = await db.get_configuration_settings(
            user_id=msg.chat.id
        )
        configuration_settings = configuration_settings[0]
    except IndexError:
        await msg.answer("❌ Пропишите /start и попробуй заново")
        return

    if configuration_settings.get("blacklist_type") == 2:
        await check_link_run_stats(links, site, msg, configuration_settings, state)

    await state.update_data(link_or_name=links)

    # avg_today, avg_this_month, avg_all_time = await get_avg_values_by_period(
    #     site, column="price"
    # )
    # add_text = generate_avg_text(
    #     avg_today,
    #     avg_this_month,
    #     "Средняя цена на площадке",
    #     # additional_avg=await get_values_from_error_stats(site, "price_decline"),
    #     mode="digit",
    # )

    await msg.answer(
        f"💰 <b>Введите диапазон цены товара:\n\nПример: 100-80000</b>",
        reply_markup=await get_price_parser_btns(
            save_type="item_price_amount",
            user_id=msg.chat.id,
            site=site,
        ),
    )

    await set_state_by_site(site, state)


async def check_link_run_stats(links, site, msg, configuration_settings, state):
    msg = msg.message if isinstance(msg, CallbackQuery) else msg

    text_push = "⚠️ Статистика запуска ссылок и слов\n\n"
    rows = await db.get_link_run_stats(site=site)
    for user_link in links.split("\n"):
        count = sum(
            user_link.casefold() in word.get("keyword").casefold() for word in rows
        )
        if count == 0:
            continue
        run_date = await db.get_last_run_date(site=site, keyword=user_link.casefold())

        try:
            text_push += f"🔍 Ссылку/Слово: <b>{user_link.casefold()}</b>\n💼 Запускали: <b>{count} раз за сегодня (другие пользователи)</b>\n⏳ Последний запуск: <b>{humanize_date(run_date)}</b>\n\n"
        except Exception:
            text_push += f"🔍 Ссылку/Слово: <b>{user_link.casefold()}</b>\n💼 Запускали: <b>{count} раз за сегодня (другие пользователи)</b>\n⏳ Последний запуск: <b>n/a</b>\n\n"

    if text_push != "⚠️ Статистика запуска ссылок и слов\n\n":
        cfg_markup = InlineKeyboardBuilder()
        await state.update_data(update_button_from_search=True)
        await state.update_data(
            text_to_update=[
                "❌ Искать только непросмотренные объявления  [1/3]%update_setting|blacklist_type",
            ]
        )
        add_check_buttons(
            cfg_markup,
            configuration_settings,
            ["blacklist_type"],
            ["Выключить этот пункт в конфигураторе"],
            ["update_setting|blacklist_type"],
        )
        await msg.answer(text_push, reply_markup=cfg_markup.as_markup())


@router.callback_query(F.data.contains("links_run"))
async def saved_links_run(query: CallbackQuery, state: FSMContext):
    row_id = query.data.split("|")[-1]

    await state.update_data(row_id=row_id)
    await set_keyword_parser(query.message, state)

    with suppress(TelegramAPIError):
        await query.answer()


@router.message(StateFilter("preset_choice"))
async def preset_choice(msg: Message, state: FSMContext):
    if msg.text == "Да":
        await msg.answer("💾 Введите название пресета: ", reply_markup=cancel_button)
        await state.set_state("set_save_preset_parser")
    elif msg.text == "Нет":
        asyncio.create_task(run_parser_in_process_pool(msg, state))
    else:
        await msg.answer(
            "❌ Указано неправильно значение, попробуйте еще раз",
            reply_markup=cancel_button,
        )


@router.message(StateFilter("set_save_preset_parser"))
async def set_save_preset_parser(msg: Message, state: FSMContext, last_parser=False):
    preset_name = "last_parser" if last_parser else validation_user_text(msg.text)
    user_data = await state.get_data()

    keys = [
        "parser_mode",
        "link_or_name",
        "site",
        "item_price_amount",
        "seller_item_amount",
        "seller_join_date",
        "item_insert_date",
        "item_views_amount",
        "item_rating_decline",
        "item_delivery_amount",
        "seller_gender",
        "seller_item_bought_amount",
        "seller_item_sold_amount",
        "item_has_delivery",
    ]

    extracted_data = {key: user_data.get(key, "") for key in keys}
    extracted_data["item_price_amount"] = user_data.get(
        "item_price_amount", "1-99999999"
    )

    if not last_parser and len(preset_name) >= LIMIT_MAX_PRESET_NAME_LENGTH:
        await msg.answer("❌ Слишком длинное название", reply_markup=cancel_button)
        return

    if not last_parser:
        user_presets = await db.get_presets(
            site=extracted_data["site"], user_id=msg.chat.id
        )

        if len(user_presets) >= LIMIT_MAX_PRESETS:
            await msg.answer(
                "❌ Пресет не был сохранен, так как лимит исчерпан",
                reply_markup=cancel_button,
            )
            return

        if user_presets:
            all_presets = user_presets[0].get("text_title")
            if preset_name in str(all_presets):
                await msg.answer(
                    "❌ Данное имя пресета занято", reply_markup=cancel_button
                )
                return

    preset_data = str(ujson.dumps(extracted_data))
    # logger.debug(preset_data)
    if last_parser:
        await db.delete_user_last_parser(msg.chat.id)

    await db.add_preset(
        site=extracted_data["site"],
        user_id=msg.chat.id,
        text_title=preset_name,
        text_body=preset_data,
    )

    if not last_parser:
        asyncio.create_task(run_parser_in_process_pool(msg, state))


MAX_SIZE = 45 * 1024 * 1024


def split_text_to_parts(text: str, max_size=MAX_SIZE):
    parts = []
    current_size = 0
    current_text = ""

    for line in text.split("\n"):
        line_size = len(line.encode("utf-8"))
        if current_size + line_size > max_size:
            parts.append(current_text)
            current_text = line + "\n"
            current_size = line_size
        else:
            current_text += line + "\n"
            current_size += line_size

    if current_text:
        parts.append(current_text)

    return parts


async def get_declined_ads(stat_id, chat_id):
    in_memory_file = BytesIO()
    # await db.create(max_size=3, min_size=1)
    history = await db.get_parser_stats_history_with_links(chat_id, stat_id)
    for row in history:
        ad_link = row.get("error_details").split("|")[0]
        error_code = row.get("error_code")

        text_segment = f"""
Товар: {ad_link}
Причина отклонения: {error_code_mapping(error_code)}
    
            """
        in_memory_file.write(text_segment.encode("utf-8"))

    in_memory_file.seek(0)
    file_content = in_memory_file.read().decode("utf-8")

    async with aiohttp.ClientSession(
            json_serialize=ujson.dumps,
            timeout=ClientTimeout(total=20),
            connector=TCPConnector(limit_per_host=10_000, limit=10_000),
    ) as sess:
        if not file_content:
            await send_text(
                text="❌ Ни одно объявление не было отклонено",
                chat_id=chat_id,
                sess=sess,
            )
            # await db.close()
            return

        for i, part in enumerate(split_text_to_parts(file_content)):
            with BytesIO() as new_in_memory_file:
                new_in_memory_file.write(part.encode("utf-8"))
                new_in_memory_file.seek(0)
                await send_document(
                    chat_id=chat_id,
                    sess=sess,
                    file_bytes=new_in_memory_file,
                    filename=f'parser-declined-part{i + 1} {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.txt',
                )
    # await db.close()


@router.callback_query(F.data.contains("get_error_result"))
async def get_error_result(query: CallbackQuery):
    stat_id = int(query.data.split("|")[-1])

    # asyncio.get_running_loop().run_in_executor(
    #     pool_process,
    #     wrapper_for_run_cpu_bound,
    #     get_declined_ads,
    #     stat_id,
    #     query.from_user.id,
    # )
    asyncio.create_task(get_declined_ads(stat_id, query.from_user.id))
    # asyncio.create_task(
    #     worker.process_pool.submit(get_declined_ads, stat_id, query.from_user.id)
    # )

    with suppress(TelegramAPIError):
        await query.answer()


async def run_parser_in_process_pool(msg, state):
    state_data = await state.get_data()
    links = state_data.get("link_or_name")
    site = state_data.get("site")
    # logger.debug(state_data)
    await state.set_state(None)
    status = await get_parser_status(msg.chat.id, redis)
    if status == "running":
        await msg.answer(
            "❌ Нельзя парсить одновременно 2 площадки", reply_markup=stop_parser
        )
        return

    await msg.answer(
        "✅ Парсинг начался, ожидайте результатов, статистика будет изменяться ниже, результат можно получить нажав на"
        " кнопку ниже\n\n<b>⚠️ Для обновления статистики нажмите на кнопку обновить статистику или дождитесь завершения парсинга</b>",
        reply_markup=stop_button,
    )

    analyze_msg = f"""
<b>💼 Анализ парсинга</b> (#code)
    Площадка: <b>{make_place_pretty_view(site)}</b>
    Поисковой запрос: <b>{links}</b>
    Получено объявлений: <b>0 шт.</b>
    Прошло: <b>0 мин. </b>
"""
    stat_id = await msg.answer(analyze_msg)
    stat_text = stat_id.text
    stat_id = stat_id.message_id

    await msg.bot.edit_message_text(
        text=stat_text.replace("#code", f"#{stat_id}"),
        chat_id=msg.chat.id,
        message_id=stat_id,
        reply_markup=get_result_btns(stat_id),
    )
    await msg.bot.pin_chat_message(chat_id=msg.chat.id, message_id=stat_id)

    await state.update_data(user_id=msg.chat.id)
    await state.update_data(stat_id=stat_id)
    await state.update_data(rerun=False)

    await set_save_preset_parser(msg, state, last_parser=True)

    await log_parser_run_for_admin(msg, site, await state.get_data(), stat_id)

    await db.add_stats_ticker(
        user_id=msg.chat.id, stat_id=stat_id, site=site, last_msg=analyze_msg
    )

    await db.add_running_parser_recovery_info(
        msg.chat.id, str(ujson.dumps(await state.get_data()))
    )

    try:
        # asyncio.get_running_loop().run_in_executor(
        #     pool_process,
        #     wrapper_for_run_cpu_bound,
        #     run_parser,
        #     await state.get_data(),
        # )
        await run_parser(await state.get_data())
        # await worker.process_pool.submit(run_parser, await state.get_data())
    except Exception:
        logger.debug(traceback.format_exc())


async def format_links(link_or_name, site):
    for link in link_or_name.split("\n"):
        if link.count("https://") > 1:
            new_link = [value for value in link.split("https://") if value]
            link_or_name = link_or_name.replace(
                link, "".join(f"https://{z}\n" for z in new_link)
            )

    link_or_name = (
        link_or_name.replace("\n\n", "\n")
        .replace("\n\n\n", "\n")
        .replace("\n\n\n\n", "\n")
    )
    for link in link_or_name.split("\n"):
        await db.add_run_stats(site=site, keyword=link)

    return link_or_name


async def run_parser(state_data):
    # logger.debug(state_data)
    parser_mode = state_data.get("parser_mode")
    site = state_data.get("site")
    watch_parser = state_data.get("watch_parser")
    chat_id = int(state_data.get("user_id"))
    stat_id = int(state_data.get("stat_id"))

    # pool = ConnectionPool(host=REDIS_HOST, password=REDIS_PASS, port=REDIS_PORT, db=0)
    # redis_ = Redis(connection_pool=pool)
    # t1_start = perf_counter()
    # redis_ = Redis(host=REDIS_HOST, password=REDIS_PASS, port=REDIS_PORT, db=0)
    # if chat_id == 384305307:
    #     logger.debug(f"redis_ connect {perf_counter() - t1_start}")

    # await db.create(max_size=3, min_size=1)

    async with aiohttp.ClientSession(
            json_serialize=ujson.dumps,
            timeout=ClientTimeout(total=20),
            connector=TCPConnector(limit_per_host=10_000, limit=10_000),
    ) as sess:
        status = await get_parser_status(chat_id, redis_)
        if status == "running" and not state_data.get("rerun"):
            await send_text(
                chat_id=chat_id,
                text="❌ Нельзя парсить одновременно 2 площадки",
                reply_markup=stop_parser_json,
                sess=sess,
            )
            # await db.close()
            await redis_.aclose()
            return

        await db.add_parser_status(chat_id, "running")
        USER_MUTEX[chat_id] = ""

        if state_data.get("tokens"):
            TOKEN_ERRORS[chat_id] = {}

        item_price = state_data.get("item_price_amount")
        if item_price == "Не использовать фильтр":
            state_data["price_from"] = state_data["price_to"] = "Не использовать фильтр"
        else:
            try:
                state_data["price_from"], state_data["price_to"] = item_price.split("-")
            except (AttributeError, ValueError):
                (
                    state_data["price_from"],
                    state_data["price_to"],
                ) = f"1-{item_price}".split("-")

        # logger.debug(state_data)
        if not site:
            logger.debug(state_data)
            await send_text(
                chat_id=chat_id,
                text="❌ Что-то пошло не так, отсутствует важный ключ при запуске",
                sess=sess,
            )
            # await db.close()
            await redis_.aclose()
            return

        if state_data.get("tokens"):
            tokens = state_data.get("tokens")
            delimetr = "\n\n" if "\n\n" in tokens else "\n"
            tokens = tokens.split(delimetr)
            state_data["tokens"] = tokens

            if len(tokens) > MAX_TOKEN:
                await send_text(
                    chat_id=chat_id,
                    text=f"❌ Нельзя добавлять больше {MAX_TOKEN} токенов",
                    sess=sess,
                )
                # await db.close()
                await redis_.aclose()
                return

            tokens_import = ";".join(tokens)

            await db.add_user_tokens(
                tokens_import,
                site,
                chat_id,
            )

        link_or_name = await format_links(state_data.get("link_or_name"), site)
        links = link_or_name.split("\n")
        links = [link for link in links if link]

        configuration_settings = await db.get_configuration_settings(chat_id)
        configuration_settings = configuration_settings[0]

        custom_text = await db.get_custom_msg_text(chat_id, site)

        filtration_words = await db.get_user_blacklisted_words(chat_id)
        if filtration_words:
            filtration_words = filtration_words.split("\n")
            filtration_words = [word for word in filtration_words if word]

        max_ads_count = min(
            LIMIT_ADS_MAX, configuration_settings.get("getter_ads_limit")
        )

        await get_items_by_place(
            site,
            chat_id,
            stat_id,
            links,
            parser_mode,
            state_data,
            configuration_settings,
            filtration_words,
            max_ads_count,
            watch_parser,
            sess,
            redis_,
            custom_text,
        )


async def get_items_by_place(
        site,
        chat_id,
        stat_id,
        links,
        parser_mode,
        state_data,
        configuration_settings,
        filtration_words,
        max_ads_count,
        watch_parser,
        sess,
        redis_,
        custom_text,
):
    t1_start = perf_counter()
    ITEMS_POOL.setdefault(chat_id, [])
    URLS_POOL.setdefault(chat_id, [])

    tasks = [
        asyncio.create_task(
            get_url_by_place(
                site,
                links,
                parser_mode,
                state_data,
                chat_id,
                max_ads_count,
                stat_id,
                redis_,
            )
        ),
        asyncio.create_task(
            get_items(
                chat_id,
                state_data,
                configuration_settings,
                stat_id,
                site,
                filtration_words,
                max_ads_count,
                t1_start,
                watch_parser,
                sess,
                redis_,
            )
        ),
        asyncio.create_task(
            pool_watcher(
                chat_id,
                site,
                stat_id,
                configuration_settings,
                state_data,
                max_ads_count,
                redis_,
                custom_text,
                filtration_words,
            )
        ),
    ]
    await asyncio.gather(*tasks)

    ticker = await db.get_all_stats_id_by_user_id(chat_id, stat_id)
    if ticker:
        ticker = ticker[0]

    await db.remove_stats_ticker(chat_id, stat_id)

    await db.add_parser_status(chat_id, "stop")

    # logger.debug("finish")
    await db.remove_running_parser_recovery_info(chat_id)
    if ticker:
        await handle_ticker(
            ticker, "no_dp", edit_time=False, remove_renew_keyboard=True, sess=sess
        )
    # await db.close()
    # await redis_.aclose()
    await send_text(
        chat_id,
        text="✅ Парсер успешно завершил свою работу, теперь посмотрите результаты",
        reply_markup=get_start_menu_markup(chat_id, json_output=True),
        sess=sess,
    )
