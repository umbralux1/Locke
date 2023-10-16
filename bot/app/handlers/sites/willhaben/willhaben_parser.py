import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import re
import traceback
import uuid
from datetime import datetime
from time import perf_counter
from urllib.parse import quote_plus, urlparse, parse_qs, urlencode, urlunparse

import jmespath
import pytz
import ujson
from bs4 import BeautifulSoup
from curl_cffi import requests, CurlError
from curl_cffi.requests import RequestsError
from loguru import logger
from tenacity import stop_after_attempt, retry
from ujson import JSONDecodeError

from app import db
from app.config import (
    ITEMS_POOL,
    URLS_POOL,
    URLS_POOL_CYCLE_SEC,
    ITEMS_POOL_CYCLE_SEC,
    PHOTO_NOT_FOUND_IMG_LINK,
    URL_HISTORY,
    URLS_POOL_WATCH_CYCLE_SEC,
    PHONE_SEARCH_ONLY,
    PHONE_SEARCH_AND_WITHOUT,
    PHONE_SEARCH_SELF,
    PHONE_SEARCH_WITHOUT_ONLY,
)
from app.misc.notify import send_text
from app.misc.parser_essintials import (
    get_random_string,
    build_url,
    encode_html,
    get_possible_phones,
    filter_date,
    apply_filter_and_add_history,
    check_on_filter_words_in_text,
    handle_subscription_expiry,
    handle_stop_signal_and_max_ads_limit,
    handle_long_parser,
    check_out_of_stock_proxy,
    filter_new_urls,
    fetch_pool_urls,
    check_worker_views_cache,
    check_person_blacklist_cache,
    wait_for_items_pool,
    generate_custom_text_for_phones,
    format_phone,
    convert_to_iso,
    increment_pagination_param,
)
from app.misc.parser_logger import send_update_get_items
from app.misc.processing import run_processing_tasks, _running_tasks
from app.misc.semaphore_control import get_semaphore_amount_by_site
from app.proxy import proxy_manager
from app.proxy.manager import AllProxyBlacklisted


async def get_urls_willhaben(
    link_or_name, parser_mode, state_data, sess, redis_, category_list
):
    price_from = state_data.get("price_from")
    price_to = state_data.get("price_to")

    query_params = {
        "ISPRIVATE": "1",
        "sort": "1",
        "isNavigation": "true",
        "rows": "100",
        "page": "1",
    }

    cat_id = "kaufen-und-verkaufen/marktplatz"
    if parser_mode == "1":
        try:
            cat_id = link_or_name.split("iad/")[1].split("?")[0]
        except Exception:
            cat_id = "kaufen-und-verkaufen/marktplatz"

    base_url = f"https://api.willhaben.at/restapi/v2/search/atz/seo/{cat_id}?"

    if parser_mode == "1":
        try:
            query = re.search(r"(keyword=)([^&/?]+)", link_or_name)[2]
        except (AttributeError, IndexError, TypeError):
            query = None

        if query:
            query_params["keyword"] = quote_plus(query)
            query_params["typedKeyword"] = quote_plus(query)
    else:
        query_params["keyword"] = quote_plus(link_or_name)
        query_params["typedKeyword"] = quote_plus(link_or_name)

    if price_to != "Не использовать фильтр":
        query_params["PRICE_FROM"] = price_from
        query_params["PRICE_TO"] = price_to
        # query_params["maxPrice"] = price_to
        # query_params["priceCurrency"] = "EUR"

    return f"{build_url(base_url, query_params)}OLD_LINK={link_or_name}"


@retry(stop=stop_after_attempt(3), reraise=True)
async def get_item_json(item_id, sess, redis_, extra_headers):
    url = f"https://publicapi.willhaben.at/atdetail/v1/{item_id}"
    proxy = await proxy_manager.get_proxy("willhaben", redis_)
    headers = extra_headers
    response = await sess.get(
        url,
        headers=headers,
        proxies={"https": proxy},
        impersonate="chrome99_android",
        timeout=9,
    )

    status_code = response.status_code
    # logger.debug(status_code)
    if status_code in [404, 410]:
        return status_code

    if status_code == 429:
        logger.debug(proxy)
        await asyncio.sleep(5)
        raise BadStatusCode(status_code)

    if status_code in [500, 403]:
        logger.debug(proxy)
        raise BadStatusCode(status_code)

    return response.json()


class BadStatusCode(Exception):
    ...


async def get_phones(
    item,
    site,
):
    try:
        phones = [item.get("contact").get("phone")]
    except Exception:
        logger.debug(item)
        phones = []

    # logger.debug(phones)

    if item.get("contact").get("phone"):
        phones = [format_phone(phone, site) for phone in phones]

    return phones


async def process_item_willhaben(
    item_id,
    site,
    stat_id,
    chat_id,
    configuration_settings,
    state_data,
    max_ads_count,
    sess,
    redis_,
    custom_text,
    filtration_words,
    extra_headers,
):
    if not await handle_stop_signal_and_max_ads_limit(
        max_ads_count, chat_id, stat_id, redis_
    ):
        return

    try:
        item = await get_item_json(item_id, sess, redis_, extra_headers)
        if item in [404, 410]:
            return
    except AllProxyBlacklisted:
        return
    except Exception:
        logger.error(traceback.format_exc())
        await db.add_parser_stats_history(
            user_id=chat_id,
            stat_id=stat_id,
            site=site,
            error_code="json_not_received",
            error_details=item_id,
        )
        return

    try:
        url = next(
            (
                x.get("uri")
                for x in item.get("contextLinks")
                if x.get("id") == "canonicalLink"
            ),
            "",
        )
    except Exception:
        logger.debug(traceback.format_exc())
        url = "https://www.google.com/"

    try:
        person_id = (
            item.get("taggingData").get("tmsDataValues").get("tmsData").get("seller_id")
        )
    except Exception:
        logger.debug(item)
        logger.error(traceback.format_exc())
        await db.add_parser_stats_history(
            user_id=chat_id,
            stat_id=stat_id,
            site=site,
            error_code="person_id_not_received",
            error_details=item_id,
        )
        return

    if not await check_person_blacklist_cache(
        configuration_settings, site, person_id, stat_id, chat_id, url, redis_
    ):
        return

    try:
        title = ""
        if configuration_settings.get("show_title"):
            title = encode_html(
                item.get("taggingData")
                .get("tmsDataValues")
                .get("tmsData")
                .get("ad_title")
            )
    except Exception:
        logger.debug(traceback.format_exc())
        title = "N/A"

    try:
        price = ""
        if configuration_settings.get("show_price"):
            price = item.get("messagingInfo").get("adInfo").get("price")
    except Exception:
        logger.debug(traceback.format_exc())
        price = "N/A"

    created_time = "N/A"
    try:
        if configuration_settings.get("show_creation_date"):
            created_time = (
                item.get("taggingData")
                .get("tmsDataValues")
                .get("tmsData")
                .get("publish_date")
            )
            # logger.debug(created_time)
    except Exception:
        logger.debug(traceback.format_exc())
        created_time = "N/A"

    try:
        description = ""
        if configuration_settings.get("show_desc"):
            description = encode_html(
                next(
                    (
                        x.get("teaser")
                        for x in item.get("widgets")
                        if x.get("type") == "PARAGRAPHED_TEXT"
                    ),
                    "",
                )
            )
    except Exception:
        logger.debug(traceback.format_exc())
        description = "N/A"

    person_registration_date = "N/A"
    try:
        if configuration_settings.get("show_person_joined"):
            person_registration_date = (
                item.get("messagingInfo").get("sellerInfo").get("userSince")
            )
            result = filter_date(
                state_data,
                configuration_settings,
                "seller_join_date",
                person_registration_date,
                "show_person_joined",
            )
            if result:
                # logger.debug(result)
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="seller_reg_date_decline",
                    error_details=f"{url}|{state_data.get('seller_join_date')}|{person_registration_date}",
                )
                return
    except Exception:
        logger.debug(traceback.format_exc())
        person_registration_date = "N/A"

    try:
        photo = ""
        if configuration_settings.get("show_photo"):
            photo = item.get("messagingInfo").get("adInfo").get("image")
    except Exception:
        photo = PHOTO_NOT_FOUND_IMG_LINK

    try:
        location = ""
        if configuration_settings.get("show_location"):
            location = (
                item.get("taggingData")
                .get("tmsDataValues")
                .get("tmsData")
                .get("region_level_3")
            )
    except Exception:
        logger.debug(traceback.format_exc())
        location = "N/A"

    try:
        person_name = ""
        if configuration_settings.get("show_person_name"):
            person_name = encode_html(
                item.get("messagingInfo").get("sellerInfo").get("userName")
            )
    except Exception:
        logger.debug(traceback.format_exc())
        person_name = "N/A"

    ads_number = "N/A"
    if configuration_settings.get("show_ads_number"):
        try:
            ads_number = (
                item.get("messagingInfo").get("sellerInfo").get("activeAdCount")
            )
        except AllProxyBlacklisted:
            return
        except Exception:
            logger.debug(traceback.format_exc())
            logger.debug(person_id)
            ads_number = "N/A"

    if configuration_settings.get("show_ads_number"):
        filter_date_str = state_data.get("seller_item_amount")
        filter_result = await apply_filter_and_add_history(
            filter_date_str,
            ads_number,
            "filter_ads_number_decline",
            db,
            chat_id,
            stat_id,
            site,
            url,
        )
        if filter_result:
            return filter_result

    if not await check_person_blacklist_cache(
        configuration_settings,
        site,
        person_id,
        stat_id,
        chat_id,
        url,
        redis_,
    ):
        return

    try:
        possible_phones = get_possible_phones(
            title,
            person_name,
            description,
            site=site,
        )
    except Exception:
        logger.debug(traceback.format_exc())
        possible_phones = ""

    worker_views = await db.get_worker_views_count(item_id=item_id, site=site)
    await db.add_parser_history(
        person_id=person_id,
        stat_id=stat_id,
        price=price,
        user_id=chat_id,
        title=title,
        ad_link=url,
        creation_date=created_time,
        description=description[:200],
        location=location,
        person_name=person_name,
        ads_number=ads_number,
        possible_phones=str(ujson.dumps(possible_phones)),
        our_views=worker_views,
        photo=photo,
        person_registration_date=person_registration_date,
        site=site,
    )

    await db.add_person_id_to_blacklist(
        user_id=chat_id, site=site, blacklisted_id=person_id
    )
    # await redis_.hset(
    #     "blacklist_persons", f"{chat_id}_{site}_{person_id}", str(person_id)
    # )
    # await redis_.hset("blacklist_persons", f"{site}_{person_id}", str(person_id))
    # await redis_.hset("user_item_views", f"{chat_id}_{item_id}_{site}", str(person_id))
    # await redis_.hset("user_item_views", f"{item_id}_{site}", str(person_id))

    if worker_views < 30:
        # await redis_.hset("worker_views", f"{item_id}_{site}", "seen")
        await db.add_item_id_to_worker_views(
            user_id=chat_id, site=site, item_id=item_id
        )


async def pre_process_item(
    item,
    max_ads_count,
    chat_id,
    stat_id,
    configuration_settings,
    site,
    state_data,
    filtration_words,
    redis_,
):
    if not await handle_stop_signal_and_max_ads_limit(
        max_ads_count, chat_id, stat_id, redis_
    ):
        return

    attributes = item.get("attributes").get("attribute")
    person_id = next(
        (x.get("values")[0] for x in attributes if x.get("name") == "ORGID"), ""
    )
    # try:
    #     url = next(
    #         (
    #             x.get("uri")
    #             for x in item.get("contextLinks")
    #             if x.get("id") == "canonicalLink"
    #         ),
    #         "",
    #     )
    # except Exception:
    #     logger.debug(traceback.format_exc())

    item_id = item.get("id")
    # logger.debug(item_id)
    # logger.debug(person_id)
    url = item_id

    # if configuration_settings.get("blacklist_type") == 2:
    #     user_view_this_item = await redis_.hget("user_item_views", f"{item_id}_{site}")
    #     code_error = "filter_blacklist_shared_decline"
    # else:
    #     user_view_this_item = await redis_.hget(
    #         "user_item_views", f"{chat_id}_{item_id}_{site}"
    #     )
    #     code_error = "filter_blacklist_decline"
    #
    # if user_view_this_item:
    #     # logger.debug(user_view_this_item)
    #     await db.add_parser_stats_history(
    #         user_id=chat_id,
    #         stat_id=stat_id,
    #         site=site,
    #         error_code=code_error,
    #         error_details=f"{url}||{str(user_view_this_item)}",
    #     )
    #     return

    if not await check_worker_views_cache(
        configuration_settings, item_id, site, url, chat_id, stat_id, redis_
    ):
        return

    if not await check_person_blacklist_cache(
        configuration_settings,
        site,
        person_id,
        stat_id,
        chat_id,
        url,
        redis_,
    ):
        return

    if configuration_settings.get("show_creation_date"):
        try:
            result = filter_date(
                state_data,
                configuration_settings,
                "item_insert_date",
                next(
                    (
                        x.get("values")[0]
                        for x in attributes
                        if x.get("name") == "CHANGED_String"
                    ),
                    "",
                ),
                "show_creation_date",
            )
            if result:
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="created_date_decline",
                    error_details=f"{url}|{state_data.get('item_insert_date')}|0",
                )
                return
        except Exception:
            logger.debug(traceback.format_exc())
    if (
        configuration_settings.get("show_price")
        and state_data.get("price_to") != "Не использовать фильтр"
    ):
        try:
            price_check = float(
                next(
                    (
                        x.get("values")[0]
                        for x in attributes
                        if x.get("name") == "PRICE/AMOUNT"
                    ),
                    "0",
                )
            )
            # logger.debug(price_check)

            price_from = float(state_data.get("price_from"))
            price_to = state_data.get("price_to", "Не использовать фильтр")

            if price_to != "Не использовать фильтр" and (
                price_check < price_from or price_check > float(price_to)
            ):
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="price_decline",
                    error_details=f"{url}|{price_from}-{price_to}|{price_check}",
                )
                return

        except Exception:
            logger.debug(traceback.format_exc())
    if configuration_settings.get("show_title"):
        try:
            title = item.get("description")
            is_have_black_word = check_on_filter_words_in_text(filtration_words, title)
            if is_have_black_word:
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="black_words_decline",
                    error_details=f"{url}||{title}",
                )
                return
        except Exception:
            logger.debug(traceback.format_exc())
    if configuration_settings.get("show_desc"):
        try:
            desc = next(
                (x.get("values")[0] for x in attributes if x.get("name") == "BODY_DYN"),
                "",
            )
            is_have_black_word = check_on_filter_words_in_text(filtration_words, desc)
            if is_have_black_word:
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="black_words_decline",
                    error_details=f"{url}||{desc}",
                )
                return
        except Exception:
            logger.debug(traceback.format_exc())

    return item


def generate_salt():
    try:
        salt = os.urandom(12)
        return base64.b64encode(salt).decode()
    except Exception as e:
        return "d7Z34msd8d9v34G"


def current_time():
    tz_moscow = pytz.timezone("Europe/Moscow")
    datetime_moscow = datetime.now(tz_moscow)
    return datetime_moscow.strftime("%Y-%m-%dT%H:%M:%S%z")


def get_hmac(timestamp: str, salt: str):
    key = f"{salt};{timestamp};api@tailored-apps.com"
    secret = hmac.new(
        "$2a$10$qTwigHZ2rRjCjRKwP.S6W.".encode(), key.encode(), digestmod=hashlib.sha1
    )
    return base64.b64encode(secret.digest()).decode().strip()


@retry(stop=stop_after_attempt(3), reraise=True)
async def gen_token(sess, redis_):
    salt = generate_salt()
    timestamp = current_time()
    proxy = await proxy_manager.get_proxy("willhaben", redis_=redis_)

    headers = {
        "Accept": "application/json",
        "X-Wh-Date": timestamp,
        "X-Wh-Client": "api@tailored-apps.com;willhabenapp;android;6.28.0;responsive_app",
        "X-Wh-Security-Version": "20130527022532",
        "Content-Type": "application/json; charset=utf-8",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": "okhttp/4.11.0",
    }
    json = {
        "applicationTokenRequest": {
            "organization": "api@tailored-apps.com",
            "salt": salt,
            "signature": get_hmac(timestamp, salt),
            "timestamp": timestamp,
        }
    }

    item = await sess.post(
        "https://api.willhaben.at/restapi/v2/application-data?config_item=search-config&config_item=root-links&config_item=tagging-plan&config_item=vertical&config_item=article&config_item=texts&config_item=app-config&config_item=image-search&config_item=advertising-config&config_item=states-districts",
        headers=headers,
        data=ujson.dumps(json),
        proxies={"https": proxy},
        impersonate="chrome99_android",
        timeout=9,
    )
    try:
        item = item.json()
    except Exception:
        logger.debug(proxy)
        logger.debug(item.status_code)
        logger.debug(item.text)

    return item.get("applicationToken").get("value"), timestamp


@retry(stop=stop_after_attempt(3), reraise=True)
async def make_req_to_get_items_willhaben(
    url,
    sess,
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
):
    if not await handle_stop_signal_and_max_ads_limit(
        max_ads_count, chat_id, stat_id, redis_
    ):
        return

    if not await wait_for_items_pool(max_ads_count, chat_id, stat_id, redis_):
        return

    # token, wh_date = await gen_token(sess, redis_)
    headers = access_token

    try:
        proxy = await proxy_manager.get_proxy("willhaben", redis_)
    except AllProxyBlacklisted:
        return

    url_req = url.split("OLD_LINK=")[0]
    url_user = url.split("OLD_LINK=")[-1]

    all_items = await sess.get(
        url_req,
        headers=headers,
        proxies={"https": proxy},
        impersonate="chrome99_android",
        timeout=9,
    )
    all_items = ujson.loads(all_items.text)
    all_items = all_items.get("advertSummaryList").get("advertSummary")

    if watch_parser:
        URLS_POOL[chat_id].extend([url])

    if all_items and not watch_parser:
        URLS_POOL[chat_id].extend(
            increment_pagination_param(
                url_req, value=1, user_link=f"OLD_LINK={url_user}", param="page"
            )
        )
    elif not all_items and not watch_parser:
        return f"❌ Ссылка {url_user} не выдала результатов, удаляю ее из парсинга, код для отладки #{stat_id}"

    # logger.debug(URLS_POOL[chat_id])

    if all_items:
        processed_items = await asyncio.gather(
            *[
                pre_process_item(
                    item,
                    max_ads_count,
                    chat_id,
                    stat_id,
                    configuration_settings,
                    site,
                    state_data,
                    filtration_words,
                    redis_,
                )
                for item in all_items
            ]
        )
        return [
            item.get("id")
            for item in processed_items
            if item and item.get("id") and item.get("id") != " "
        ]
