import asyncio
import traceback

import aiohttp
from aiohttp import FormData
from loguru import logger
from tenacity import stop_after_attempt, retry, wait_fixed

from app.config import BOT_TOKEN

REPLY_MARKUP = {
    "stop_parser": {
        "keyboard": [[{"text": "❌ Завершить парсинг", "callback_data": "stop_parser"}]],
        "resize_keyboard": True,
    }
}


@retry(stop=stop_after_attempt(3), wait=wait_fixed(3), reraise=True)
async def send_data(url, data, sess):
    try:
        result = None

        if isinstance(data, FormData):
            result = await sess.post(url, data=data)
        else:
            result = await sess.post(url, json=data)

        return result
    except (asyncio.TimeoutError, aiohttp.client.ClientResponseError):
        logger.debug("timeout error")
        logger.debug(data)
        logger.debug(url)
    except Exception:
        logger.debug(traceback.format_exc())

        if result:
            logger.debug(await result.text())


async def send_text(chat_id, text, reply_markup=None, sess=None):
    if not text:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return await send_data(url, data, sess)


async def send_photo(
    chat_id,
    photo,
    caption,
    reply_markup=None,
):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    data = {
        "chat_id": chat_id,
        "photo": photo,
        "caption": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return await send_data(
        url,
        data,
    )


async def send_video(chat_id, video, caption, reply_markup=None, sess=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    data = {
        "chat_id": chat_id,
        "video": video,
        "caption": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return await send_data(url, data, sess=sess)


async def edit_message_text(chat_id, message_id, new_text, sess, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return await send_data(url, data, sess)


async def send_document(chat_id, file_bytes, filename, sess=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    data = FormData()
    data.add_field("chat_id", str(chat_id))
    data.add_field(
        "document",
        file_bytes,
        filename=filename,
        content_type="application/octet-stream",
    )

    # logger.debug(chat_id)
    return await send_data(url, data, sess)
