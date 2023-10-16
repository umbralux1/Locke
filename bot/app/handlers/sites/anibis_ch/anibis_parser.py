import asyncio
import json
import random
import re
import traceback
from time import perf_counter
from urllib.parse import quote_plus, urlparse, parse_qs, urlencode, urlunparse

import jmespath
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


@retry(stop=stop_after_attempt(5), reraise=True)
async def get_cat_id(url, sess, redis):
    proxy = await proxy_manager.get_proxy("anibis", redis_=redis)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://www.anibis.ch/fr",
        "Sec-Fetch-Dest": "script",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
        "Te": "trailers",
        "Connection": "close",
    }

    async with sess.get(
        url,
        headers=headers,
        proxy=proxy,
    ) as response:
        html = await response.text()

    try:
        soup = BeautifulSoup(html, "lxml")
        script = (
            soup.find("script", {"id": "state"})
            .get_text(strip=True)
            .replace("window.__INITIAL_STATE__ = ", "")
            .split('"searchParameter": "')[-1]
            .split("&cid=")[-1]
            .split('",')[0]
        )
        return script
    except Exception:
        logger.debug(traceback.format_exc())
        return 1


async def get_urls_anibis(
    link_or_name, parser_mode, state_data, sess, redis_, category_list
):
    price_from = state_data.get("price_from")
    price_to = state_data.get("price_to")

    query_params = {
        "pi": 1,
        "sf": "dpo",
        "so": "d",
        "ps": "200",
    }
    base_url = "https://api.anibis.ch/v4/fr/search/listings?"

    if parser_mode == "1":
        try:
            query = re.search(r"(fts=)([^&/?]+)", link_or_name)[2]
        except (AttributeError, IndexError, TypeError):
            query = None

        try:
            cat_id = await get_cat_id(link_or_name, sess, redis_)
        except Exception:
            logger.debug(traceback.format_exc())
            logger.debug(link_or_name)
            cat_id = None

        if not str(cat_id).isdigit():
            cat_id = 1
        # logger.debug(cat_id)

        if query:
            query_params["fts"] = quote_plus(query)
        if cat_id:
            query_params["cid"] = cat_id
    else:
        query_params["fts"] = quote_plus(link_or_name)

    if price_to != "Не использовать фильтр":
        query_params["aral"] = f"834_{price_from}_{price_to}"
        # query_params["maxPrice"] = price_to
        # query_params["priceCurrency"] = "EUR"

    # logger.debug(f"{build_url(base_url, query_params)}")
    return f"{build_url(base_url, query_params)}OLD_LINK={link_or_name}"


@retry(stop=stop_after_attempt(5), reraise=True)
async def get_item_json(item_id, sess, redis_):
    url = f"https://api.anibis.ch/v4/fr/listings/{item_id}"
    proxy = await proxy_manager.get_proxy("anibis", redis_)
    headers = {
        "Accept": "application/json; charset=utf-8",
        "User-Agent": "ch.anibis.anibis/7.26.0 (Android 8.0.0; Android Google; rv:532150) XHDPI",
        "User-Os": "Android",
        "Accept-Language": "fr",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    async with sess.get(
        url,
        headers=headers,
        proxy=proxy,
    ) as response:
        status_code = response.status
        if status_code in [404, 410]:
            return status_code

        if status_code in [500, 403]:
            logger.debug(proxy)
            raise BadStatusCode(status_code)

        return await response.json()


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


async def process_item_anibis(
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
    # if chat_id == 384305307:
    #     logger.debug("i in process item anibis")

    if not await handle_stop_signal_and_max_ads_limit(
        max_ads_count, chat_id, stat_id, redis_
    ):
        return

    try:
        item = await get_item_json(item_id, sess, redis_)
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
        url = "https://anibis.ch" + item.get("languageUrls").get("fr")
    except Exception:
        logger.debug(traceback.format_exc())
        url = "https://www.google.com/"

    if configuration_settings.get("phone_search_type") in [
        PHONE_SEARCH_ONLY,
        PHONE_SEARCH_SELF,
    ] and not item.get("contact").get("phone"):
        await db.add_parser_stats_history(
            user_id=chat_id,
            stat_id=stat_id,
            site=site,
            error_code="no_seller_phone",
            error_details=f"{url}|{configuration_settings.get('phone_type')}|{item.get('contact').get('phone')}",
        )
        return

    if configuration_settings.get(
        "phone_search_type"
    ) == PHONE_SEARCH_WITHOUT_ONLY and item.get("contact").get("phone"):
        await db.add_parser_stats_history(
            user_id=chat_id,
            stat_id=stat_id,
            site=site,
            error_code="no_seller_phone",
            error_details=f"{url}|{configuration_settings.get('phone_type')}|{item.get('contact').get('phone')}",
        )
        return

    try:
        if not item.get("seller"):
            await db.add_parser_stats_history(
                user_id=chat_id,
                stat_id=stat_id,
                site=site,
                error_code="business_seller_decline",
                error_details=url,
            )
            return
        person_id = item.get("seller").get("id")
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
            title = encode_html(item.get("title"))
    except Exception:
        logger.debug(traceback.format_exc())
        title = "N/A"

    try:
        price = ""
        if configuration_settings.get("show_price"):
            price = item.get("formattedPrice")
    except Exception:
        logger.debug(traceback.format_exc())
        price = "N/A"

    created_time = "N/A"
    try:
        if configuration_settings.get("show_creation_date"):
            created_time = convert_to_iso(item.get("formattedModified"))
            # logger.debug(created_time)
    except Exception:
        logger.debug(traceback.format_exc())
        created_time = "N/A"

    try:
        description = ""
        if configuration_settings.get("show_desc"):
            description = encode_html(item.get("description"))
    except Exception:
        logger.debug(traceback.format_exc())
        description = "N/A"

    person_registration_date = "N/A"
    try:
        if configuration_settings.get("show_person_joined"):
            person_registration_date = convert_to_iso(
                item.get("seller").get("registrationDate").split()[-1]
            )
            # logger.debug(person_registration_date)
            # logger.debug(seller_join_date)
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
            photo = item.get("imageData").get("baseUrl") + item.get("imageData").get(
                "images"
            )[0].replace("[size]", "1024x768/3/60")
    except Exception:
        photo = PHOTO_NOT_FOUND_IMG_LINK

    try:
        location = ""
        if configuration_settings.get("show_location"):
            location = item.get("location").get("country")
    except Exception:
        logger.debug(traceback.format_exc())
        location = "N/A"

    try:
        person_name = ""
        if configuration_settings.get("show_person_name"):
            person_name = encode_html(item.get("seller").get("name"))
    except Exception:
        logger.debug(traceback.format_exc())
        person_name = "N/A"

    ads_number = "N/A"
    if configuration_settings.get("show_ads_number"):
        try:
            ads_number = item.get("seller").get("amountOfActiveListings")
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
        # logger.debug("yeah lol i am work")
        return

    custom_texts = ""
    if configuration_settings.get("phone_search_type") in [
        PHONE_SEARCH_ONLY,
        PHONE_SEARCH_AND_WITHOUT,
    ]:
        try:
            phones = await get_phones(
                item,
                site,
            )
        except Exception:
            logger.debug(traceback.format_exc())
            phones = []
            if configuration_settings.get("phone_search_type") == PHONE_SEARCH_ONLY:
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="phone_getter_error",
                    error_details=f"{url}|{configuration_settings.get('phone_type')}|0",
                )
                return
        if phones:
            custom_texts = await generate_custom_text_for_phones(
                custom_text,
                phones,
                url,
                person_name,
                price,
                title,
                chat_id,
                sess,
                configuration_settings.get("only_person_wa"),
                site,
                stat_id,
            )
            # logger.debug(custom_texts)
            if not custom_texts:
                return

    try:
        possible_phones = get_possible_phones(
            item.get("title"),  # item.get("title").get("value")
            item.get("seller").get("name"),
            item.get("description"),
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
        person_link=url + "#conversation",
        user_id=chat_id,
        phone=str(ujson.dumps(custom_texts)),
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

    try:
        url = "https://anibis.ch/" + item.get("staticUrl")
    except Exception:
        logger.debug(traceback.format_exc())
        url = "https://www.google.com/"

    item_id = item.get("id")

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

    if configuration_settings.get("show_creation_date"):
        try:
            result = filter_date(
                state_data,
                configuration_settings,
                "item_insert_date",
                convert_to_iso(item.get("detailsMainLarge")[-1]),
                "show_creation_date",
            )
            if result:
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code="created_date_decline",
                    error_details=f"{url}|{state_data.get('item_insert_date')}|{convert_to_iso(item.get('detailsMainLarge')[-1])}",
                )
                return
        except Exception:
            logger.debug(traceback.format_exc())
    if (
        configuration_settings.get("show_price")
        and state_data.get("price_to") != "Не использовать фильтр"
    ):
        try:
            price_check = float(item.get("price"))
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
            ...
            # logger.debug(traceback.format_exc())
    if configuration_settings.get("show_title"):
        try:
            title = item.get("title")
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
            desc = item.get("detailsExtraLarge")
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


@retry(stop=stop_after_attempt(5), reraise=True)
async def make_req_to_get_items_anibis(
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

    headers = {
        "Accept": "application/json; charset=utf-8",
        "User-Agent": "ch.anibis.anibis/7.26.0 (Android 8.0.0; Android Google; rv:532150) XHDPI",
        "User-Os": "Android",
        "Accept-Language": "fr",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }

    try:
        proxy = await proxy_manager.get_proxy("anibis", redis_)
    except AllProxyBlacklisted:
        return

    # logger.debug(proxy)

    url_req = url.split("OLD_LINK=")[0]
    url_user = url.split("OLD_LINK=")[-1]

    async with sess.get(
        url_req,
        headers=headers,
        proxy=proxy,
    ) as response:
        all_items = await response.json()
    all_items = all_items.get("listings", [])

    if watch_parser:
        URLS_POOL[chat_id].extend([url])

    if all_items and not watch_parser:
        URLS_POOL[chat_id].extend(
            increment_pagination_param(
                url_req, value=1, user_link=f"OLD_LINK={url_user}", param="pi"
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
