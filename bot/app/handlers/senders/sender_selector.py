import asyncio
import random
import secrets
import traceback
import uuid
from contextlib import suppress
from urllib.parse import unquote_plus

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bs4 import BeautifulSoup
from curl_cffi import requests
from loguru import logger
from tenacity import stop_after_attempt, retry

from app import dp, db, redis
from app.config import MANUALS, BANNER_VIDEO, SENDER_STATUS_DB
from app.keyboards.cancel import cancel_button
from app.keyboards.custom_text_menu import get_user_custom_text_buttons
from app.keyboards.site_actions import stop_sender_button
from app.misc.semaphore_control import handler_grouper_by_site
from app.proxy import proxy_manager

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("auto_sender"))
async def format_result(query: CallbackQuery):
    stat_id = int(query.data.split("|")[-1])

    history = await db.get_user_parser_history(
        stat_id=stat_id, user_id=query.from_user.id
    )
    if not history:
        await query.message.answer("❌ Ни один товар не был найден")
        return

    site = history[0].get("site")
    await query.message.answer(
        """
У нас так же есть отдельный бот, созданный специально для рассылок, с отдельным пулом прокси, с возможностью выбора скорости рассылки, с возможностью остелижвания диалога, авто ответы и многое другое - @1\n
🤖 Как это работает?

▶️ Мы подключимся через к вашему аккаунту и на все аккаунты, которые вы только что спарсили, в ЛС будет отправлен ваш текст

▶️ Мы не несем ответственности за текст, который вы будете рассылать

▶️ Мы не несем ответственности за Ваш аккаунт

▶️ Сервис не имеет никаких обязательств перед пользователями 

▶️ Нажимая продолжить, Вы автоматически соглашаетесь со всеми условиями предоставленными выше
""",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Продолжить",
                        callback_data=f"sender_start|{site}|{stat_id}",
                    )
                ],
            ]
        ),
    )


@router.callback_query(F.data.contains("sender_start"))
async def sender_start(query: CallbackQuery, state: FSMContext):
    stat_id = int(query.data.split("|")[-1])
    site = query.data.split("|")[-2]

    if handler_grouper_by_site(site) not in ["olx", "ebay.de"]:
        await query.message.answer(
            "❌ Рассылка не поддерживается для этого сайта, но если много людей будут интересоваться этим (пишите в ТП) мы постараемся добавить"
        )
        return

    with suppress(TelegramBadRequest):
        await query.message.edit_text(
            f"""
🤖 Введите ваши куки от аккаунта

▶️ Мануал по получению куки {MANUALS[handler_grouper_by_site(site)]}"""
        )
    await state.set_state("get_cookie_sender")
    await state.update_data(stat_id=stat_id)
    await state.update_data(site=site)


@dp.message(StateFilter("get_cookie_sender"))
async def get_ebay_cookie(msg: types.Message, state: FSMContext):
    if len(msg.text) < 35:
        await msg.answer("❌ Ты отправляешь неверные куки", reply_markup=cancel_button)
        return

    state_data = await state.get_data()
    site = state_data.get("site")
    await state.update_data(cookie=msg.text)

    if site == "ebay.de":
        await msg.answer("▶️ Укажите имя от которого будет рассылать")
        await state.set_state("get_contact_name_ebay")
        return

    user_text = await db.get_custom_msg_text(msg.from_user.id, site)
    await state.update_data(cookie_olx=msg.text)
    await state.update_data(show_callback="text_sender")
    await msg.answer_video(
        video=BANNER_VIDEO,
        caption="""
🤖 Выберите какой текст рассылать
            """,
        reply_markup=get_user_custom_text_buttons(
            site,
            user_text=user_text,
            sender_select=True,
            show_callback="text_sender",
        ),
    )


@dp.message(StateFilter("get_contact_name_ebay"))
async def get_contact_name_ebay(msg: types.Message, state: FSMContext):
    try:
        await state.update_data(contact_name=msg.text)
        user_data = await state.get_data()
        site = user_data.get("site")

        user_text = await db.get_custom_msg_text(msg.from_user.id, site)
        await state.update_data(show_callback="text_sender")
        await msg.answer_video(
            video=BANNER_VIDEO,
            caption="""
🤖 Выберите какой текст рассылать
        """,
            reply_markup=get_user_custom_text_buttons(
                site,
                user_text=user_text,
                sender_select=True,
                show_callback="text_sender",
            ),
        )
    except Exception:
        logger.debug(traceback.format_exc())
        await msg.answer("❌ Что-то пошло не так")


@router.callback_query(F.data.contains("text_sender"))
async def sender_start(query: CallbackQuery, state: FSMContext):
    user_id_str = str(query.from_user.id)
    text_name, site = query.data.split("|")[-2:]

    user_data = await state.get_data()
    stat_id = user_data.get("stat_id")
    if not stat_id:
        await query.message.answer("❌ Что-то пошло не так, попробуйте заново")
        return

    cookie_ebay = user_data.get("cookie")
    contact_name = user_data.get("contact_name")
    items_to_send = await db.get_items_for_sender(stat_id)

    if not items_to_send:
        return await query.message.answer("❌ Нет объявлений для рассылки")

    await state.clear()
    with suppress(TelegramBadRequest):
        await query.message.edit_caption(
            "✅ Начинаю рассылку", reply_markup=stop_sender_button
        )

    asyncio.create_task(
        sender_run(
            user_id_str,
            site,
            text_name,
            query,
            items_to_send,
            cookie_ebay,
            contact_name,
        )
    )


@retry(stop=stop_after_attempt(3), reraise=True)
async def send_message_ebay(item_url, text, cookie, contact_name, sess, site):
    item_id = item_url.split("/")[-1].split("-")[0]
    url = "https://www.kleinanzeigen.de/s-anbieter-kontaktieren.json"
    csrf = str(uuid.uuid4())
    cookies = {"CSRF-TOKEN": csrf, "access_token": cookie}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Csrf-Token": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.kleinanzeigen.de",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Te": "trailers",
    }
    data = {
        "message": text,
        "adId": item_id,
        "adType": "private",
        "contactName": contact_name,
    }
    proxy = await proxy_manager.get_proxy("ebay", redis)
    person = await sess.post(
        url,
        headers=headers,
        proxies={"https": proxy},
        impersonate="safari15_5",
        cookies=cookies,
        data=data,
    )
    return person.status_code


# def base62_to_decimal(s):
#     s = s[2:]
#     chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUWVXYZ"
#     return sum(chars.index(c) * (62**i) for i, c in enumerate(reversed(s)))


@retry(stop=stop_after_attempt(5), reraise=True)
async def resolve_id(url, redis, sess):
    proxy = await proxy_manager.get_proxy("olx", redis)
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
        "Accept-Language": "ru",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }

    html = await sess.get(
        url,
        headers=headers,
        proxies={"https": proxy},
        impersonate="safari15_5",
    )

    soup = BeautifulSoup(html.text, "lxml")
    return (
        soup.find("div", {"data-cy": "ad-footer-bar-section"})
        .find("span")
        .text.split()[-1]
    )


@retry(stop=stop_after_attempt(3), reraise=True)
async def send_message_olx(item_url, text, cookie, contact_name, sess, site):
    cookies = {"access_token": cookie}
    try:
        item_id = await resolve_id(item_url, redis, sess)
        # logger.debug(item_id)
    except Exception:
        # logger.error(f"Error resolving ID: {traceback.format_exc()}")
        return 403

    site_code = site.split(".")[-1]
    url = f"https://api.chat.olx.{site_code}/api/conversations"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15",
        "Accept": "*/*",
        "Accept-Language": "pt-PT, pt",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
        "X-Client": "DESKTOP",
        "X-Client-Version": "d87b31c8_2484313",
        "X-Site-Code": f"olx{site_code}",
        "Origin": f"https://www.olx.{site_code}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Authorization": f"Bearer {cookie}",
        "Referer": f"https://www.olx.{site_code}/",
        "Te": "trailers",
    }
    json = {
        "ad_id": int(item_id),
        "message": {"message_id": str(uuid.uuid4()), "text": text},
    }
    proxy = await proxy_manager.get_proxy("olx", redis)
    person = await sess.post(
        url,
        headers=headers,
        proxies={"https": proxy},
        impersonate="safari15_5",
        cookies=cookies,
        json=json,
    )
    if person.status_code in [429, 401]:
        return person.status_code

    if person.status_code != 200:
        logger.debug(person.status_code)
        logger.debug(person.text)
        logger.debug(json)
        logger.debug(item_url)
        logger.debug(headers)
        logger.debug(cookies)
        logger.debug(proxy)
        logger.debug(url)

    return person.status_code


func_mapping = {
    "ebay.de": send_message_ebay,
    "olx": send_message_olx,
}


async def sender_run(
    user_id_str, site, text_name, query, items_to_send, cookie_ebay, contact_name
):
    SENDER_STATUS_DB[user_id_str] = "work"

    custom_text_list = (
        await db.get_custom_msg_text(site=site, user_id=user_id_str)
        if text_name == "any"
        else []
    )
    text_wa = (
        await db.get_custom_msg_text_by_title(
            user_id=user_id_str, site=site, text_title=text_name
        )
        if text_name != "any"
        else None
    )

    if text_wa is None and not custom_text_list:
        return await query.message.answer(
            "❌ Нужен хоть один кастомный текст или текст не найден"
        )

    cookies = cookie_ebay.split("\n")
    async with requests.AsyncSession(max_clients=10000) as sess:
        for item in items_to_send:
            if SENDER_STATUS_DB[user_id_str] == "stop":
                break

            item_url, seller_name, item_price, item_name = item

            text_wa_selected = (
                secrets.choice(custom_text_list).get("text_body")
                if text_name == "any"
                else text_wa
            )
            text_wa_edited = unquote_plus(
                f"{text_wa_selected.replace('%40link', item_url).replace('%40sellername', seller_name).replace('%40price', item_price).replace('%40itemname', item_name)}"
            )

            cookie = secrets.choice(cookies)

            try:
                result = await func_mapping[handler_grouper_by_site(site)](
                    item_url, text_wa_edited, cookie, contact_name, sess, site
                )
            except Exception:  # замените на конкретное исключени
                logger.debug(traceback.format_exc())
                result = 403

            if result == 429:
                await query.message.answer(
                    "⚠️ Рассылка будет завершена, так как лимит рассылок исчерпан на вашем аккаунте OLX"
                )
                SENDER_STATUS_DB[user_id_str] = "stop"
                break
            if result == 401:
                await query.message.answer(
                    "⚠️ Рассылка будет завершена, так как токен не авторизован"
                )
                SENDER_STATUS_DB[user_id_str] = "stop"
                break

            status_text = "✅ Смс отправлено" if result == 200 else "❌ Смс не отправлено"
            await query.message.answer(
                f"📲 Продавец: {item_url}\n💬 Текст: {text_wa_edited}\nСтатус отправки: {status_text}",
                reply_markup=stop_sender_button,
            )
            await asyncio.sleep(random.randint(5, 10))

    await query.message.answer("✅ Рассылка успешно завершена")
    SENDER_STATUS_DB[user_id_str] = "stop"
