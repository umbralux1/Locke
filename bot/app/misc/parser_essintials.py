import asyncio
import re
import secrets
import string
import traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from time import perf_counter
from typing import Optional
from urllib.parse import (
    unquote,
    unquote_plus,
    quote,
    urlparse,
    parse_qs,
    urlunparse,
    urlencode,
)

import aiohttp
import ciso8601
import pytz
import ujson
import uvloop
from loguru import logger
from tenacity import retry, stop_after_attempt

from app import db
from app.config import (
    MAX_PARSER_TIME_IN_MIN,
    URLS_POOL,
    BANNER_VIDEO,
    MAX_PARSER_TIME_IN_MIN_WATCH,
    BL_UNSEEN_ONLY,
    BL_SHARED,
    WHATSAPP_CHECK_LIMIT_PER_DAY,
    WA_CHECK_USER,
    WA_CHECK_API,
    ITEMS_POOL,
)
from app.keyboards.site_actions import get_result_btns
from app.misc.notify import send_text, send_video, edit_message_text
from app.misc.phone_codes import PHONE_PREFIX_BY_COUNTRY
from app.misc.processing import cancel_processing_tasks
from app.proxy import proxy_manager
from app.proxy.manager import AllProxyBlacklisted


def get_random_string(lenf):
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(lenf)
    )


def build_url(base_url, params):
    return base_url + "&".join([f"{key}={value}" for key, value in params.items()])


def encode_html(text):
    if not text:
        return text

    # Удаляем HTML тэги
    text = re.sub(r"<.*?>", "", text)

    # Заменяем спец символы, но оставляем \n и двоеточия (чтобы не сломать ссылки)
    text = re.sub(r'[&*\'"]', " ", text)

    return text


def error_code_mapping(error_code):
    mapping = {
        "json_not_received": "Ошибка получения json",
        "filter_delivery_count_decline": "Кол-во успешных доставок",
        "filter_delivery_decline": "Отсутсвие/Наличие доставки",
        "created_date_decline": "Дата создания",
        "no_seller_phone": "Нет номера телефона",
        "phone_getter_error": "Ошибка получения номера",
        "bad_token": "Ошибка токена",
        "price_decline": "Цена",
        "phone_whatsapp_decline": "Продавца нет в WhatsApp",
        "filter_blacklist_shared_decline": "Общий черный список",
        "filter_blacklist_decline": "Черный список",
        "filter_views_decline": "Просмотры товара",
        "item_has_many_worker_views": "Искать только непросмотренные товары",
        "filter_ads_number_decline": "Кол-во товаров продавца",
        "filter_seller_item_sold_amount": "Кол-во проданных товаров",
        "filter_seller_item_bought_amount": "Кол-во купленных товаров",
        "black_words_decline": "Запрещенные слова",
        "person_id_not_received": "Ошибка получения user id",
        "business_seller_decline": "Тип продавца",
        "seller_reg_date_decline": "Дата регистрации продавца",
        "wrong_country_decline": "Неверная страна товара",
        "gender_decline": "Гендер продавца",
        "rating_decline": "Рейтинг продавца",
    }
    # logger.debug(error_code)
    return mapping.get(error_code, "Неизвестная ошибка")


def get_possible_phones(title="", description="", person_name="", site=""):
    place = site.split(".")[-1].replace("uk", "gb")

    if title is None:
        title = ""
    if description is None:
        description = ""
    if person_name is None:
        person_name = ""

    # Удаляем ненужные символы
    remove_chars = " \n-|()_/=."
    trans = str.maketrans("", "", remove_chars)
    text = (
        (title + description + person_name)
        .translate(trans)
        .replace("O", "0")
        .replace("О", "0")
    )

    # Ищем возможные номера телефонов
    phones = re.findall(
        r"\+?\d{0,4}[\s.-]?\(?\d{1,4}?\)?[\s.-]?\d{1,4}[\s.-]?\d{1,4}[\s.-]?\d{0,4}",
        text,
    )

    # Форматируем и фильтруем номера
    phones = [format_phone(phone, place) for phone in phones if 9 <= len(phone) < 15]

    return list(set(phones))


def format_phone(phone, country_code):
    # Удаляем лишние символы

    phone = re.sub(r"[ -()/-]", "", phone)

    # Получаем код страны

    country_code = country_code.split(".")[-1].upper()

    dial_code = next(
        (c["dial_code"] for c in PHONE_PREFIX_BY_COUNTRY if c["code"] == country_code),
        "",
    ).replace("+", "")

    # Обработка для Казахстана

    if country_code == "KZ":
        phone = re.sub(r"^(?:\+?87|\+?70|\+?78|87|78|70)", "77", phone)

    # Убираем старый код страны и код оператора, если они уже есть

    phone = phone.lstrip("+")

    if phone.startswith(dial_code):
        phone = phone[len(dial_code) :]

    # Убираем первые две цифры внутреннего кода, если они начинают строку

    phone = re.sub(r"^0{1,2}", "", phone)

    # Добавляем нужный dial_code

    phone = f"+{dial_code}{phone}"

    return phone


def parse_datetime_with_tzinfo(date_str, fmt, timezone=None):
    dt = pytz.utc.localize(datetime.strptime(date_str, fmt))
    if timezone:
        dt = dt.astimezone(timezone)
    return dt


def check_date_in_range(start_date, end_date, target_date):
    if start_date <= target_date <= end_date:
        return True


def filter_date(
    state_data: dict,
    configuration_settings: dict,
    key_state: str,
    item_date_value: str,
    log_tag: str,
) -> Optional[str]:
    filter_date_str = state_data.get(key_state)
    # logger.debug(filter_date_str)
    show_item = configuration_settings.get(log_tag)

    if show_item and (
        filter_date_str
        and filter_date_str != "Не использовать фильтр"
        and item_date_value != "N/A"
    ):
        item_date = ciso8601.parse_datetime(item_date_value)
        if item_date.tzinfo is None or item_date.tzinfo.utcoffset(item_date) is None:
            item_date = item_date.replace(tzinfo=timezone.utc)

        if ":" in filter_date_str:
            start_str, end_str = filter_date_str.split(":")
            start_date = parse_datetime_with_tzinfo(
                start_str, "%d-%m-%Y", item_date.tzinfo
            )
            end_date = parse_datetime_with_tzinfo(end_str, "%d-%m-%Y", item_date.tzinfo)

            try:
                if not check_date_in_range(start_date, end_date, item_date):
                    return f"filter_{key_state}_decline"
            except Exception:
                logger.debug(filter_date_str)
                logger.debug(start_date)
                logger.debug(end_date)
                logger.debug(item_date)
        else:
            date1 = parse_datetime_with_tzinfo(
                filter_date_str, "%d-%m-%Y", item_date.tzinfo
            )

            # logger.debug(date1)
            # logger.debug(item_date)
            days_left = (date1 - item_date).days
            if days_left > 0:
                return f"filter_{key_state}_decline"


async def apply_filter_and_add_history(
    filter_str, value, error_code, db, chat_id, stat_id, site, url
):
    if filter_str and filter_str != "Не использовать фильтр" and value != "N/A":
        if "-" in filter_str:
            start_value, end_value = filter_str.split("-")

            if not check_date_in_range(int(start_value), int(end_value), int(value)):
                await db.add_parser_stats_history(
                    user_id=chat_id,
                    stat_id=stat_id,
                    site=site,
                    error_code=error_code,
                    error_details=f"{url}|{filter_str}|{value}",
                )
                return error_code
        elif int(filter_str) < int(value):
            await db.add_parser_stats_history(
                user_id=chat_id,
                stat_id=stat_id,
                site=site,
                error_code=error_code,
                error_details=f"{url}|{filter_str}|{value}",
            )
            return error_code


def check_on_filter_words_in_text(filters_words, text):
    if filters_words and text:
        text_casefold = str(text).casefold()
        for word in filters_words:
            if str(word).casefold() in text_casefold:
                return "found_blacklist_word"


async def get_parser_status(chat_id, redis):
    return await db.get_user_parser_status(chat_id)


def decode_and_split_urls(url_list):
    decoded_urls = [unquote(str(url)) for url in url_list]
    return "\n\n".join(decoded_urls)


async def send_large_text(chat_id, text, semaphore, chunk_size=4096):
    for start in range(0, len(text), chunk_size):
        async with semaphore:
            await send_text(chat_id=chat_id, text=text[start : start + chunk_size])


async def handle_subscription_expiry(chat_id, site, stat_id, sess, redis):
    expiry_date = await db.get_user_subscription_site(site=site, user_id=chat_id)
    if not expiry_date or expiry_date and expiry_date < datetime.now():
        await db.add_parser_status(chat_id, "stop")
        await send_video(
            chat_id,
            video=BANNER_VIDEO,
            caption=f"⚠️ Парсинг будет завершен, так как у вас кончилась подписка, код для отладки #{stat_id}",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "💰 Продлить подписку",
                            "callback_data": f"renew_subscription|{site}",
                        }
                    ]
                ]
            },
            sess=sess,
        )
        return

    return True


async def handle_ticker(
    ticker, dp, edit_time=True, remove_renew_keyboard=False, sess=None
):
    await edit_ticker_message(ticker, dp, edit_time, remove_renew_keyboard, sess)


DECLINE_TEXT = """
<b>Причины отклонения объявлений</b>
"""


async def edit_ticker_message(ticker, dp, edit_time, remove_renew_keyboard, sess):
    chat_id = ticker.get("user_id")
    msg_id = ticker.get("stat_id")
    date = ticker.get("date")
    text = ticker.get("last_msg")

    current_time = datetime.now()
    time_diff = current_time - date

    # t1_start = time.perf_counter()
    minutes, seconds = divmod(time_diff.total_seconds(), 60)
    new_text = re.sub(
        r"(Прошло:\s*<b>\s*)(\d+)(\s*мин\.\s*</b>)",
        lambda m: f"{m.group(1)}{minutes} мин. {round(seconds)} сек.</b>",
        text,
    )

    received_item_count = await db.get_count_received_item(chat_id, msg_id)
    new_text = re.sub(
        r"(Получено объявлений:\s*<b>\s*)(\d+)(\s*шт\.\s*</b>)",
        lambda m: f"{m.group(1)}{received_item_count}{m.group(3)}",
        new_text,
    )
    # logger.debug(f"{chat_id}/{msg_id} regular time: {time.perf_counter() - t1_start}")

    # t1_start = time.perf_counter()
    history = await db.get_parser_stats_history(user_id=chat_id, stat_id=msg_id)
    # logger.debug(f"{chat_id}/{msg_id} db time get_parser_stats_history: {time.perf_counter() - t1_start}")
    if history and DECLINE_TEXT not in new_text:
        new_text += DECLINE_TEXT

    # t1_start = time.perf_counter()
    error_count_dict = {}
    for row in history:
        human_error_code = error_code_mapping(row.get("error_code"))
        if human_error_code in error_count_dict:
            error_count_dict[human_error_code] += 1
        else:
            error_count_dict[human_error_code] = 1
    # logger.debug(f"{chat_id}/{msg_id} cycle time error_code_mapping: {time.perf_counter() - t1_start}")

    # t1_start = time.perf_counter()
    for human_error_code, error_count in error_count_dict.items():
        pattern = re.compile(rf"{re.escape(human_error_code)}: <b>\d+</b>")
        if pattern.search(new_text):
            new_text = pattern.sub(
                f"{human_error_code}: <b>{error_count}</b>", new_text
            )
        else:
            new_text += f"    {human_error_code}: <b>{error_count}</b>\n"

    await edit_message_text(
        chat_id,
        msg_id,
        new_text.replace("#code", f"#{msg_id}"),
        sess,
        reply_markup=get_result_btns(
            msg_id, json_output=True, remove_renew_keyboard=remove_renew_keyboard
        ),
    )


async def handle_stop_signal_and_max_ads_limit(max_ads_count, chat_id, stat_id, redis):
    t1 = perf_counter()
    status = await get_parser_status(chat_id, redis)
    if chat_id == 384305307:
        logger.debug(f"{chat_id}/{stat_id} get_parser_status: {perf_counter() - t1}")
    if status == "stop":
        return
    if status == "stop_fast":
        cancel_processing_tasks()
        return
    t1 = perf_counter()
    received_item_count = await db.get_count_received_item(chat_id, stat_id)
    if received_item_count >= max_ads_count:
        await db.add_parser_status(chat_id, "stop")
        return

    if chat_id == 384305307:
        logger.debug(
            f"{chat_id}/{stat_id} get_count_received_item: {perf_counter() - t1}"
        )

    return True


async def handle_long_parser(t1_start, chat_id, stat_id, watch_parser, sess, redis):
    if watch_parser:
        stop_time = MAX_PARSER_TIME_IN_MIN_WATCH
    else:
        stop_time = MAX_PARSER_TIME_IN_MIN

    if round((perf_counter() - t1_start) / 60, 2) >= stop_time:
        await db.add_parser_status(chat_id, "stop")
        await send_text(
            chat_id,
            text=f"⚠️ Парсинг будет завершен, так как вы парсите очень долго, код для отладки #{stat_id}",
            sess=sess,
        )
        return

    return True


async def check_out_of_stock_proxy(chat_id, stat_id, proxy_name, sess, redis_):
    try:
        await proxy_manager.get_proxy(proxy_name, redis_)
    except AllProxyBlacklisted:
        await db.add_parser_status(chat_id, "stop")
        await send_text(
            chat_id,
            text=f"⚠️ Парсинг будет завершен, так как наши прокси, для данной площадки, неактивны, пожалуйста, "
            f"обратитесь в ТП за дальнейшей помощью, код для отладки #{stat_id}",
            sess=sess,
        )
        return

    return True


def filter_new_urls(pool_urls, url_history):
    normalized_history_urls = {unquote(str(url)).lower() for url in url_history}

    pool_urls = [
        url
        for url in pool_urls
        if unquote(str(url)).lower() not in normalized_history_urls
    ]

    unique_full_urls = []
    seen_base_urls = set()
    for url in pool_urls:
        if isinstance(url, dict):
            base_url = {k: v for k, v in url.items() if k != "OLD_LINK"}
        else:
            base_url = url.split("OLD_LINK")[0]

        if str(base_url) not in seen_base_urls:
            unique_full_urls.append(url)
            seen_base_urls.add(str(base_url))
        # logger.debug(url)
        # logger.debug(pool_urls)

    url_history += unique_full_urls

    # logger.debug(unique_full_urls)
    return unique_full_urls


async def fetch_pool_urls(chat_id, stop_count):
    # logger.debug(URLS_POOL)
    if chat_id not in URLS_POOL or not URLS_POOL[chat_id]:
        return None, stop_count + 1

    pool_urls = URLS_POOL[chat_id][:]
    del URLS_POOL[chat_id][: len(pool_urls)]
    # logger.debug(URLS_POOL)

    return pool_urls, 0


async def check_worker_views_cache(
    configuration_settings, item_id, site, url, chat_id, stat_id, redis
):
    if configuration_settings.get("blacklist_type") == BL_UNSEEN_ONLY:
        # worker_views = await redis.hget("worker_views", f"{item_id}_{site}")
        worker_views = None
        if worker_views is None:
            worker_views = await db.get_worker_views_count(item_id=item_id, site=site)

        if worker_views:
            await db.add_parser_stats_history(
                user_id=chat_id,
                stat_id=stat_id,
                site=site,
                error_code="item_has_many_worker_views",
                error_details=f"{url}|0|{worker_views}",
            )
            return

    return True


async def check_person_blacklist_cache(
    configuration_settings, site, person_id, stat_id, chat_id, url, redis
):
    if configuration_settings.get("blacklist_type") == BL_SHARED:
        # is_person_id_blacklisted = await redis.hget(
        #     "blacklist_persons", f"{site}_{person_id}"
        # )
        is_person_id_blacklisted = None
        if is_person_id_blacklisted is None:
            is_person_id_blacklisted = await db.is_person_id_blacklisted_user_shared(
                person_id=person_id, site=site
            )

        if is_person_id_blacklisted:
            await db.add_parser_stats_history(
                user_id=chat_id,
                stat_id=stat_id,
                site=site,
                error_code="filter_blacklist_shared_decline",
                error_details=f"{url}||{str(person_id)}",
            )
            return
    else:
        # is_person_id_blacklisted = await redis.hget(
        #     "blacklist_persons", f"{chat_id}_{site}_{person_id}"
        # )
        is_person_id_blacklisted = None
        if is_person_id_blacklisted is None:
            is_person_id_blacklisted = await db.is_person_id_blacklisted_user(
                user_id=chat_id, person_id=person_id, site=site
            )

        if is_person_id_blacklisted:
            await db.add_parser_stats_history(
                user_id=chat_id,
                stat_id=stat_id,
                site=site,
                error_code="filter_blacklist_decline",
                error_details=f"{url}||{str(person_id)}",
            )
            return

    return True


pool_process = ProcessPoolExecutor()
pool_thread = ThreadPoolExecutor()


def wrapper_for_run_cpu_bound(func, *args, **kwargs):
    new_loop = uvloop.new_event_loop()
    new_loop.slow_callback_duration = 0.800
    asyncio.set_event_loop(new_loop)
    # setattr(underlying_transport, "_start_tls_compatible", True)
    new_loop.run_until_complete(func(*args, **kwargs))


def replace_custom_tags(raw_text, item_url, seller_name, item_price, item_name):
    return (
        raw_text.replace("%40link", item_url)
        .replace("%40sellername", seller_name)
        .replace("%40price", item_price)
        .replace("%40itemname", item_name)
    )


class WANotChecked(Exception):
    ...


@retry(stop=stop_after_attempt(3), reraise=True)
async def check_whatsapp_v3(phone, tg_user_id, sess):
    if not phone.replace("+", "").isdigit():
        return "❌"
    if len(phone.replace("+", "")) > 13:
        return "❌"
    if len(phone.replace("+", "")) < 10:
        return "❌"

    payload = {
        "user": WA_CHECK_USER,
        "apikey": WA_CHECK_API,
        "number": f"{phone.replace('+', '')}",
    }
    if isinstance(sess, aiohttp.client.ClientSession):
        async with sess.post(
            "https://w2.checkwa.com/fast/",
            json=payload,
        ) as response:
            wa_status = await response.json()
    else:
        wa_status = await sess.post(
            "https://w2.checkwa.com/fast/",
            json=payload,
            impersonate="safari15_5",
            timeout=9,
        )
        wa_status = ujson.loads(wa_status.text)

    await db.add_wa_credits(tg_user_id)

    if not wa_status.get("code"):
        raise WANotChecked

    return "✅" if wa_status.get("code") == "1" else "❌"


async def check_wa_status(tg_user_id, phone, whatsapp_only, sess):
    wa_status = "⬛️"
    if whatsapp_only:
        try:
            if (
                await db.get_wa_credits(tg_user_id, days="1")
                >= WHATSAPP_CHECK_LIMIT_PER_DAY
            ):
                wa_status = "⬛️ Limit"
            else:
                wa_status = await check_whatsapp_v3(phone, tg_user_id, sess)
        except Exception:
            logger.error(traceback.format_exc())
            wa_status = "⬛️"

    return "wa_is_broken" if wa_status == "wa_is_broken" else wa_status


async def generate_custom_text_for_phones(
    custom_text,
    phones,
    item_url,
    seller_name,
    item_price,
    item_name,
    tg_user_id,
    sess,
    whatsapp_only,
    site,
    stat_id,
):
    all_texts = []
    all_contact_texts = []
    whatsapp_texts = []
    whatsapp_statuses = []

    for phone in phones:
        if phone is None:
            continue

        wa_status = None
        if whatsapp_only:
            wa_status = await check_wa_status(tg_user_id, phone, whatsapp_only, sess)
            if wa_status == "wa_is_broken":
                wa_status = "⬛️"
            whatsapp_statuses.append(wa_status)

        if custom_text:  # Только если есть кастомные тексты
            wa_links = []
            for name, raw_text in custom_text:
                processed_text = quote(
                    unquote_plus(
                        unquote(
                            replace_custom_tags(
                                raw_text, item_url, seller_name, item_price, item_name
                            )
                        )
                    )
                )
                # logger.debug(processed_text)
                wa_link = f"<a href='https://api.whatsapp.com/send?phone={phone}&text={processed_text}'>📱*тык*</a>/<a href='https://web.whatsapp.com/send?phone={phone}&text={processed_text}'>🖥 *тык*</a> ({name})"
                wa_links.append(wa_link)
            wa_links_str = "\n".join(wa_links)
            wa_status_str = (
                f"<b>•</b> WhatsApp {wa_status}:" if wa_status else "<b>•</b> WhatsApp:"
            )
            wa_text_block = f"{wa_status_str}\n{wa_links_str}"
        else:
            wa_link = f"<a href='https://api.whatsapp.com/send?phone={phone}'>📱*тык*</a>/<a href='https://web.whatsapp.com/send?phone={phone}'>🖥 *тык*</a>"
            wa_text_block = f"<b>•</b> WhatsApp: {wa_link}"

        whatsapp_texts.append(wa_text_block)

        viber_link = f"<a href='https://viber.click/{phone}'>📱*тык*</a>"
        telegram_link = f"<a href='https://t.me/{phone}'>📱*тык*</a>"
        all_texts.extend(
            (
                f"<b>•</b> Viber: {viber_link}",
                f"<b>•</b> Telegram: {telegram_link}",
            )
        )

        all_contact_texts.append(f"<code>{phone}</code>")

    if whatsapp_only and all("❌" in status for status in whatsapp_statuses):
        await db.add_parser_stats_history(
            user_id=tg_user_id,
            stat_id=stat_id,
            site=site,
            error_code="phone_whatsapp_decline",
            error_details=f"{item_url}||0",
        )
        return

    has_custom_texts = len(custom_text) > 0
    whatsapp_texts = (
        "\n\n".join(whatsapp_texts) if has_custom_texts else "\n".join(whatsapp_texts)
    )
    all_texts = "\n".join(all_texts)

    formatted_texts = (
        f"{whatsapp_texts}\n\n{all_texts}"
        if has_custom_texts
        else f"{whatsapp_texts}\n{all_texts}"
    )

    return {
        "all_texts": formatted_texts + "\n",
        "contact_text": ";".join(all_contact_texts),
    }


async def wait_for_items_pool(max_ads_count, chat_id, stat_id, redis_):
    while len(ITEMS_POOL.get(chat_id)) >= 600:
        if not await handle_stop_signal_and_max_ads_limit(
            max_ads_count, chat_id, stat_id, redis_
        ):
            return

        await asyncio.sleep(5)

    return True


def convert_to_iso(date_str):
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    return dt.isoformat()


# def increment_pagination_param(url, value, user_link="", param=""):
#     parsed_url = urlparse(url)
#     query_params = parse_qs(parsed_url.query)
#
#     page_value = int(query_params.get(param, [0])[0])
#     incremented_page = page_value + value
#     query_params[param] = incremented_page
#
#     new_query_string = urlencode(query_params, doseq=True)
#
#     return [
#         urlunparse(
#             (
#                 parsed_url.scheme,
#                 parsed_url.netloc,
#                 parsed_url.path,
#                 parsed_url.params,
#                 new_query_string,
#                 parsed_url.fragment,
#             )
#         )
#         + user_link
#     ]
def increment_pagination_param(url, value, user_link="", param=""):
    parsed_url = urlparse(url)
    query_params = parse_qs(
        parsed_url.query, keep_blank_values=True
    )  # keep_blank_values=True сохранит пустые параметры

    page_value = int(query_params.get(param, [0])[0])
    incremented_page = page_value + value
    query_params[param] = [incremented_page]  # Не забудь обернуть значение в список

    new_query_string = urlencode(
        query_params, doseq=True
    )  # Используем doseq=True, чтобы правильно обработать списки

    return [
        urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                new_query_string,
                parsed_url.fragment,
            )
        )
        + user_link
    ]


def replace_cursor_in_link(url, param, value, user_link=""):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params[param] = value

    new_query_string = urlencode(query_params, doseq=True)

    new_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query_string,
            parsed_url.fragment,
        )
    )

    return new_url + user_link
