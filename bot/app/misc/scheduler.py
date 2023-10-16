import asyncio
import time
import traceback
from contextlib import suppress
from datetime import datetime, timedelta

import aiohttp
import ujson
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import TCPConnector
from aiohttp_socks import ProxyConnector
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger
from tenacity import retry, stop_after_attempt

from app import scheduler_, db, bot, redis
from app.config import (
    CHATS,
    ADMINS,
    BANNER_VIDEO,
    MAX_PARSER_TIME_IN_MIN_WATCH,
    SENDER_STATUS_DB,
)
from app.handlers.admin_actions.cash_report import count_payments
from app.handlers.format_result import write_msg
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.start_menu_markup import get_start_menu_markup
from app.misc.notify import send_text
from app.misc.parser_essintials import (
    get_parser_status,
)
from app.misc.semaphore_control import handler_grouper_by_site
from app.proxy import proxy_manager
from app.proxys import PROXY_ALL, PROXY_FOR_CHECK_ALL


async def check_end_subscription():
    subscriptions = await db.get_all_subscriptions_site()
    # logger.debug(subscriptions)
    for sub in subscriptions:
        site = sub.get("site")
        user_id = sub.get("user_id")
        expiry_date = sub.get("expiry_date")
        if not expiry_date or expiry_date and expiry_date < datetime.now():
            await db.remove_subscription(
                site=site,
                user_id=int(user_id),
            )

            with suppress(TelegramAPIError):
                await bot.send_video(
                    chat_id=user_id,
                    video=BANNER_VIDEO,
                    caption=f"{make_place_pretty_view(site)} истекла подписка",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="💰 Продлить подписку",
                                    callback_data=f"renew_subscription|{site}",
                                ),
                            ],
                        ]
                    ),
                )
            await asyncio.sleep(0.3)


async def get_day():
    payments = await db.get_payments(days=1)
    if not payments:
        return

    push_text = await count_payments(payments, "💼 Продажи за сегодня:\n\n")
    if len(push_text) > 4096:
        for x in range(0, len(push_text), 4096):
            await bot.send_message(
                chat_id=CHATS.get("logs"), text=push_text[x : x + 4096]
            )
    else:
        await bot.send_message(chat_id=CHATS.get("logs"), text=push_text)


async def reminder_server():
    today = datetime.now().day

    if today in [21, 22, 23]:
        days_left = 23 - today
        if days_left > 1:
            message = f"Продли сервер через {days_left} дня.\n\nhttps://cp.1.ru/operation/list"
        elif days_left == 1:
            message = "Продли сервер завтра.\n\nhttps://cp.1.ru/operation/list"
        else:
            message = "Сегодня сервер должен быть окончен.\n\nhttps://cp.1.ru/operation/list"

        await bot.send_message(chat_id=ADMINS[0], text=message)


@retry(stop=stop_after_attempt(3), reraise=True)
async def reminder_proxy6():
    async with aiohttp.ClientSession(
        raise_for_status=True,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=9),
        connector=ProxyConnector.from_url(PROXY_FOR_CHECK_ALL, rdns=False),
    ) as cs:
        async with cs.get(
            "https://1.1/api/1-1-1/getproxy/?state=expiring",
        ) as req:
            response = await req.json(content_type=None)

    response = response.get("list")
    if response:
        await bot.send_message(
            chat_id=ADMINS[0],
            text="Есть истекающие прокси на https://1.1/user/proxy",
        )


@retry(stop=stop_after_attempt(3), reraise=True)
async def reminder_proxy_seller_io():
    async with aiohttp.ClientSession(
        raise_for_status=True,
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=9),
        connector=ProxyConnector.from_url(PROXY_FOR_CHECK_ALL, rdns=False),
    ) as cs:
        async with cs.get(
            "https://1-1.io/personal/api/v1/1/proxy/list/",
        ) as req:
            response = await req.json(content_type=None)
            response = response.get("data").get("ipv4")

    if any(x["status_type"] == "ENDING" for x in response):
        await bot.send_message(
            chat_id=ADMINS[0],
            text="Есть истекающие прокси на https://1-1.io/personal/orders/",
        )


@retry(stop=stop_after_attempt(3), reraise=True)
async def target_proxy_login(headers, cookies, sess):
    async with sess.post(
        "https://1.com/login",
        headers=headers,
        data={"login": "1@1.ru", "password": "1"},
        cookies=cookies,
        allow_redirects=False,
    ) as req:
        return req.cookies.get("JSESSIONID").value


@retry(stop=stop_after_attempt(3), reraise=True)
async def target_proxy_new(headers, cookies, sess):
    async with sess.get(
        "https://1.com/app/new",
        headers=headers,
        cookies=cookies,
    ) as req:
        ...


@retry(stop=stop_after_attempt(3), reraise=True)
async def target_proxy_get_proxy_list(headers, cookies, sess):
    async with sess.get(
        "https://1.com/api/proxy/list",
        headers=headers,
        cookies=cookies,
    ) as req:
        return await req.json()


async def reminder_proxy_target_proxy():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/117.0",
        "Accept": "application/json",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Te": "trailers",
        "Connection": "close",
    }
    cookies = {
        "1": "fb.1.1.12872763",
    }

    try:
        async with aiohttp.ClientSession(
            raise_for_status=True,
            json_serialize=ujson.dumps,
            timeout=aiohttp.ClientTimeout(total=9),
            connector=ProxyConnector.from_url(PROXY_FOR_CHECK_ALL, rdns=False),
        ) as sess:
            auth_cookie = await target_proxy_login(headers, cookies, sess)
            cookies["JSESSIONID"] = auth_cookie
            await target_proxy_new(headers, cookies, sess)
            proxy_list = await target_proxy_get_proxy_list(headers, cookies, sess)

        for proxy in proxy_list:
            date_object = datetime.strptime(
                proxy.get("dateEnd")[:19], "%Y-%m-%dT%H:%M:%S"
            )
            current_date = datetime.now()
            delta = date_object - current_date

            if 0 < delta.total_seconds() < timedelta(days=3).total_seconds():
                await bot.send_message(
                    chat_id=ADMINS[0],
                    text="Есть истекающие прокси на https://targetproxy.com/app/proxy",
                )
                break
    except Exception:
        logger.debug(traceback.format_exc())
        await bot.send_message(
            chat_id=ADMINS[0],
            text="Ошибка получения targetproxy",
        )


proxy_semaphore = asyncio.Semaphore(10)


async def make_proxy_check_request(proxy, cs):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Te": "trailers",
    }

    try:
        # logger.debug(proxy)
        async with proxy_semaphore:
            start_time = time.perf_counter()
            async with cs.get(
                "https://www.google.com/",
                headers=headers,
                proxy=f"http://{proxy}",
            ) as req:
                end_time = time.perf_counter()
                time_res = end_time - start_time
                logger.debug(time_res)
                response = req.status
    except Exception as e:
        logger.debug(traceback.format_exc())
        time_res = 0
        response = "failed"

    return response, proxy, time_res


async def proxy_check():
    proxy_to_check = PROXY_ALL
    async with aiohttp.ClientSession(
        json_serialize=ujson.dumps,
        timeout=aiohttp.ClientTimeout(total=10),
        connector=TCPConnector(limit_per_host=500, limit=500),
    ) as cs:
        proxy_result = await asyncio.gather(
            *(make_proxy_check_request(proxy, cs=cs) for proxy in proxy_to_check)
        )

        # logger.debug(proxy_result)
        status = ""
        for response, proxy, time_res in proxy_result:
            if response == "failed" or time_res >= 10:
                await proxy_manager.blacklist_proxy(proxy, redis_=redis)
            else:
                await proxy_manager.enable_proxy(proxy, redis_=redis)

            status += f"{round(time_res, 2)}s. {response} {proxy}\n"

        if len(status) > 4096:
            for x in range(0, len(status), 4096):
                await send_text(CHATS.get("logs"), status[x : x + 4096], sess=cs)
        else:
            await send_text(CHATS.get("logs"), status, sess=cs)


async def delete_old_stat_id_editor():
    # logger.info("[+] delete_old_stat_id_editor started")
    old_trackers = await db.get_old_stats_id_editor(
        minutes=MAX_PARSER_TIME_IN_MIN_WATCH
    )
    if old_trackers:
        for track in old_trackers:
            stat_id = track.get("stat_id")
            chat_id = track.get("user_id")
            logger.debug(f"stopped tracker {stat_id} for user {chat_id} cuz limit")
            await db.remove_stats_ticker(chat_id, stat_id)


async def clear_redis_old_data():
    for table in [
        "user_item_views",
        "worker_views",
        "blacklist_persons",
        "running_parser_recovery_info",
    ]:
        keys = await redis.hkeys(table)
        if keys:
            logger.debug(f"clearing redis table {table} - {len(keys)} keys")
            await redis.hdel(table, *keys)


async def send_msg_to_user(user_id, stat_id, redis, bot, db, processed_stats):
    msg_sent = await redis.hget("user_offset_for_auto_msg", f"{user_id}_{stat_id}")
    msg_sent = int(msg_sent.decode()) if msg_sent else 0
    seen_items = set()
    SENDER_STATUS_DB[str(user_id)] = "work"
    # logger.debug(SENDER_STATUS_DB)

    while True:
        if SENDER_STATUS_DB[str(user_id)] == "stop":
            # processed_stats.remove((user_id, stat_id))
            await redis.hdel("user_offset_for_auto_msg", f"{user_id}_{stat_id}")
            break

        status = await get_parser_status(user_id, redis)
        if status != "running":
            received_item_count = await db.get_count_received_item(user_id, stat_id)
            # logger.debug(f"offset for {user_id}: {msg_sent}")
            # logger.debug(f"count_received_item for {user_id}: {received_item_count}")
            if msg_sent >= received_item_count:
                # processed_stats.remove((user_id, stat_id))
                await redis.hdel("user_offset_for_auto_msg", f"{user_id}_{stat_id}")

                if msg_sent:
                    with suppress(TelegramForbiddenError):
                        await bot.send_message(
                            chat_id=user_id,
                            text="✅ Вы получили все сообщения",
                            reply_markup=get_start_menu_markup(user_id),
                        )

                break

        # logger.debug(f"offset for {user_id}: {msg_sent}")
        parser_history_ = []
        parser_history = await db.get_user_parser_history_offset(
            user_id, stat_id, msg_sent
        )
        if parser_history:
            msg_sent += len(parser_history)
            await redis.hset(
                "user_offset_for_auto_msg", f"{user_id}_{stat_id}", msg_sent
            )
            for item in parser_history:
                if item.get("id") not in seen_items:
                    parser_history_.append(item)
                    seen_items.add(item.get("id"))
                    # logger.debug(f"skip {item.get('id')} cuz already sent")
                    # logger.debug(seen_items)

            await write_msg(bot, parser_history_, user_id)

        await asyncio.sleep(5)
    # logger.debug('exit')


processed_stats = set()


async def send_msg_after_find():
    rows = await db.get_stats_id_where_old_msg_enable()
    # logger.debug(processed_stats)
    for row in rows:
        user_id = row.get("user_id")
        stat_id = row.get("stat_id")
        if (user_id, stat_id) not in processed_stats:
            processed_stats.add((user_id, stat_id))
            asyncio.create_task(
                send_msg_to_user(user_id, stat_id, redis, bot, db, processed_stats)
            )


async def release_throttled_proxy():
    throttled_proxy = await db.get_throttled_proxy()
    if throttled_proxy:
        for record in throttled_proxy:
            proxy = record.get("proxy")
            site = record.get("site")
            await db.remove_throttled_proxy(proxy, handler_grouper_by_site(site))
            # logger.debug(f"release_throttled_proxy {proxy}")


async def run_scheduler_jobs():
    # scheduler_.remove_all_jobs()

    if not scheduler_.get_job("check_end_subscription"):
        scheduler_.add_job(
            check_end_subscription,
            "interval",
            seconds=3600,
            id="check_end_subscription",
        )
    if not scheduler_.get_job("send_msg_after_find"):
        scheduler_.add_job(
            send_msg_after_find,
            "interval",
            seconds=5,
            id="send_msg_after_find",
        )
    if not scheduler_.get_job("reminder_server"):
        scheduler_.add_job(
            reminder_server, trigger=IntervalTrigger(days=1), id="reminder_server"
        )
    if not scheduler_.get_job("clear_redis_old_data"):
        scheduler_.add_job(
            clear_redis_old_data,
            trigger=IntervalTrigger(days=5),
            id="clear_redis_old_data",
        )
    if not scheduler_.get_job("reminder_proxy6"):
        scheduler_.add_job(
            reminder_proxy6,
            trigger=IntervalTrigger(days=1),
            id="reminder_proxy6",
        )
    if not scheduler_.get_job("reminder_proxy_seller_io"):
        scheduler_.add_job(
            reminder_proxy_seller_io,
            trigger=IntervalTrigger(days=1),
            id="reminder_proxy_seller_io",
        )
    if not scheduler_.get_job("reminder_proxy_target_proxy"):
        scheduler_.add_job(
            reminder_proxy_target_proxy,
            trigger=IntervalTrigger(days=1),
            id="reminder_proxy_target_proxy",
        )
    if not scheduler_.get_job("proxy_check"):
        scheduler_.add_job(proxy_check, "interval", seconds=3600, id="proxy_check")
    if not scheduler_.get_job("release_throttled_proxy"):
        scheduler_.add_job(
            release_throttled_proxy,
            "interval",
            seconds=60,
            id="release_throttled_proxy",
        )
    if not scheduler_.get_job("get_day"):
        scheduler_.add_job(get_day, "cron", hour=23, minute=50, id="get_day")
    if not scheduler_.get_job("delete_old_stat_id_editor"):
        scheduler_.add_job(
            delete_old_stat_id_editor,
            "interval",
            seconds=300,
            id="delete_old_stat_id_editor",
        )
