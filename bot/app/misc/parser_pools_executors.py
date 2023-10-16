import asyncio
import traceback
import uuid

import aiohttp
import ujson
from aiohttp import ClientSession
from curl_cffi import requests
from loguru import logger

from app import db
from app.config import (
    URLS_POOL,
    ITEMS_POOL,
    ITEMS_POOL_CYCLE_SEC,
    URL_HISTORY,
    URLS_POOL_WATCH_CYCLE_SEC,
    URLS_POOL_CYCLE_SEC,
    TOKEN_ERRORS,
    ssl_context,
    USER_MUTEX,
)
from app.handlers.sites.anibis_ch.anibis_parser import (
    get_urls_anibis,
    process_item_anibis,
    make_req_to_get_items_anibis,
)


from app.handlers.sites.willhaben.willhaben_parser import (
    make_req_to_get_items_willhaben,
    process_item_willhaben,
    get_urls_willhaben,
    gen_token,
)
from app.misc.notify import send_text
from app.misc.parser_essintials import (
    handle_stop_signal_and_max_ads_limit,
    handle_subscription_expiry,
    check_out_of_stock_proxy,
    handle_long_parser,
    fetch_pool_urls,
    filter_new_urls,
)
from app.misc.parser_logger import send_update_get_items
from app.misc.processing import run_processing_tasks, _running_tasks
from app.misc.semaphore_control import (
    get_semaphore_amount_by_site,
    handler_grouper_by_site,
)

func_mapping = {
    "anibis.ch": {
        "get_urls": get_urls_anibis,
        "process_item": process_item_anibis,
        "make_req_to_get_items": make_req_to_get_items_anibis,
    },
    "willhaben.at": {
        "get_urls": get_urls_willhaben,
        "process_item": process_item_willhaben,
        "make_req_to_get_items": make_req_to_get_items_willhaben,
    },
}

aiohttp_sessions = ["wallapop", "anibis.ch", "depop", "subito.it", "carousell", "olx"]


async def handle_stop_count(chat_id, stop_count, stat_id, sess_aio, redis_):
    if not URLS_POOL[chat_id] and not _running_tasks and not ITEMS_POOL[chat_id]:
        if stop_count >= 30:
            await db.add_parser_status(chat_id, "stop")
            await send_text(
                chat_id,
                text=f"⚠️ Парсер завершает свою работу, так как в течении долгого времени не было найдено новых объявлений, код для отладки #{stat_id}",
                sess=sess_aio,
            )
            return True, stop_count
        stop_count += 1
    return False, stop_count


async def handle_mutex_token(chat_id, redis_, sess_aio, stat_id):
    mutex = USER_MUTEX[chat_id]
    if mutex:
        add_text = "".join(
            f"{token[:150]} - <b>{TOKEN_ERRORS[chat_id][token]}</b>\n\n"
            for token in TOKEN_ERRORS[chat_id]
        )
        await send_text(
            chat_id=chat_id,
            text=f"❌ Все токены закончились, парсинг будет завершен, код для отладки #{stat_id}\n\n{add_text}",
            sess=sess_aio,
        )


async def get_url_by_place(
    site, links, parser_mode, state_data, chat_id, max_ads_count, stat_id, redis_
):
    async def main_logic(session):
        category_list = []

        if handler_grouper_by_site(site) == "olx":
            category_list = (
                await get_cat_list(site.split(".")[-1], session, redis_)
                if parser_mode == "1"
                else []
            )

        tasks = [
            asyncio.create_task(
                func_mapping[handler_grouper_by_site(site)]["get_urls"](
                    link.strip(),
                    parser_mode,
                    state_data,
                    sess=session,
                    redis_=redis_,
                    category_list=category_list,
                )
            )
            for link in links
        ]
        for future in asyncio.as_completed(tasks):
            result = await future
            if result:
                URLS_POOL[chat_id].append(result)

    if not await handle_stop_signal_and_max_ads_limit(
        max_ads_count, chat_id, stat_id, redis_
    ):
        return

    if handler_grouper_by_site(site) in aiohttp_sessions:
        async with ClientSession(
            json_serialize=ujson.dumps,
            timeout=aiohttp.ClientTimeout(total=9),
            connector=aiohttp.TCPConnector(ssl=ssl_context, limit=100),
        ) as session:
            await main_logic(session)
    else:
        async with requests.AsyncSession(max_clients=10000) as session:
            await main_logic(session)


async def pool_watcher(
    chat_id,
    site,
    stat_id,
    configuration_settings,
    state_data,
    max_ads_count,
    redis_,
    custom_text,
    filtration_words,
):
    async def main_logic(session):
        if site == "willhaben.at":
            token, wh_date = await gen_token(session, redis_)
            extra_headers = {
                "Accept": "application/json",
                "X-Wh-Date": wh_date,
                "X-Wh-Client": "api@tailored-apps.com;willhabenapp;android;6.3.1;responsive_app",
                "X-Wh-Visitor-Id": str(uuid.uuid4()),
                "X-Wh-Security-Version": "20130527022532",
                "X-Wh-Application-Token": token,
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "okhttp/4.10.0",
            }
        else:
            extra_headers = {}

        await run_processing_tasks(
            semaphore_amount,
            *(
                func_mapping[handler_grouper_by_site(site)]["process_item"](
                    item,
                    site,
                    stat_id,
                    chat_id,
                    configuration_settings,
                    state_data,
                    max_ads_count,
                    session,
                    redis_,
                    custom_text,
                    filtration_words,
                    extra_headers,
                )
                for item in pool_items
            ),
        )

    while True:
        if not await handle_stop_signal_and_max_ads_limit(
            max_ads_count, chat_id, stat_id, redis_
        ):
            return

        if chat_id in ITEMS_POOL and ITEMS_POOL[chat_id]:
            pool_items = ITEMS_POOL[chat_id][:]
            del ITEMS_POOL[chat_id][: len(pool_items)]

            if pool_items:
                if not isinstance(pool_items[0], dict):
                    pool_items = list(set(pool_items))
                    if None in pool_items or " " in pool_items or "" in pool_items:
                        logger.debug(pool_items)
                        pool_items = [
                            item for item in pool_items if item and item != " "
                        ]

                semaphore_amount = await get_semaphore_amount_by_site(site, pool_items)
                if handler_grouper_by_site(site) in aiohttp_sessions:
                    async with ClientSession(
                        json_serialize=ujson.dumps,
                        timeout=aiohttp.ClientTimeout(total=9),
                        connector=aiohttp.TCPConnector(ssl=ssl_context, limit=100),
                    ) as session:
                        await main_logic(session)
                else:
                    async with requests.AsyncSession(max_clients=10000) as session:
                        await main_logic(session)

        await asyncio.sleep(ITEMS_POOL_CYCLE_SEC)


async def get_items(
    chat_id,
    state_data,
    configuration_settings,
    stat_id,
    site,
    filtration_words,
    max_ads_count,
    t1_start,
    watch_parser,
    sess_aio,
    redis_,
):
    async def main_logic(session):
        if site == "willhaben.at":
            token, wh_date = await gen_token(session, redis_)
            access_token = {
                "Accept": "application/json",
                "X-Wh-Date": wh_date,
                "X-Wh-Client": "api@tailored-apps.com;willhabenapp;android;6.3.1;responsive_app",
                "X-Wh-Visitor-Id": str(uuid.uuid4()),
                "X-Wh-Security-Version": "20130527022532",
                "X-Wh-Application-Token": token,
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "okhttp/4.10.0",
            }
        else:
            access_token = ""

        tasks = [
            asyncio.create_task(
                func_mapping[handler_grouper_by_site(site)]["make_req_to_get_items"](
                    url,
                    session,
                    max_ads_count,
                    chat_id,
                    stat_id,
                    configuration_settings,
                    site,
                    state_data,
                    filtration_words,
                    watch_parser,
                    sess_aio,
                    redis_,
                    access_token,
                )
            )
            for url in pool_urls
        ]
        for future in asyncio.as_completed(tasks):
            result = await future
            if isinstance(result, str) and result not in used_text:
                used_text.append(result)
                error_text.append(result)
            elif not isinstance(result, str) and result:
                ITEMS_POOL[chat_id].extend(result)

        await send_text(
            chat_id,
            text="\n\n".join(list(set(error_text))),
            sess=sess_aio,
        )

    stop_count = 0
    used_text = []
    while True:
        await handle_mutex_token(chat_id, redis_, sess_aio, stat_id)

        if not await handle_stop_signal_and_max_ads_limit(
            max_ads_count, chat_id, stat_id, redis_
        ):
            return

        if not await handle_subscription_expiry(
            chat_id, site, stat_id, sess_aio, redis_
        ):
            return

        if not await check_out_of_stock_proxy(
            chat_id,
            stat_id,
            proxy_name=site.split(".")[0],
            sess=sess_aio,
            redis_=redis_,
        ):
            return

        if not await handle_long_parser(
            t1_start, chat_id, stat_id, watch_parser, sess_aio, redis_
        ):
            return

        should_stop, stop_count = await handle_stop_count(
            chat_id, stop_count, stat_id, sess_aio, redis_
        )
        if should_stop:
            return

        pool_urls, stop_count = await fetch_pool_urls(chat_id, stop_count)
        # logger.debug(pool_urls)
        if pool_urls is None:
            await asyncio.sleep(1)
            continue

        # logger.debug(pool_urls)
        if not watch_parser:
            pool_urls = filter_new_urls(pool_urls, URL_HISTORY)

        # logger.debug(pool_urls)
        await send_update_get_items(pool_urls, stat_id)

        try:
            error_text = []
            if handler_grouper_by_site(site) in aiohttp_sessions:
                async with ClientSession(
                    json_serialize=ujson.dumps,
                    timeout=aiohttp.ClientTimeout(total=9),
                    connector=aiohttp.TCPConnector(ssl=ssl_context, limit=100),
                ) as session:
                    await main_logic(session)
            else:
                async with requests.AsyncSession(max_clients=10000) as session:
                    await main_logic(session)

        except Exception:
            logger.error(traceback.format_exc())
            await send_text(
                chat_id,
                text=f"❌ Ошибка при запуске, парсинг будет завершен код для отладки #{stat_id}",
                sess=sess_aio,
            )

        timeout = URLS_POOL_WATCH_CYCLE_SEC if watch_parser else URLS_POOL_CYCLE_SEC
        await asyncio.sleep(timeout)
