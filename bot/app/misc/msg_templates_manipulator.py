import re
import traceback

import ujson
from loguru import logger

from app import db, redis

OLD_TEMPLATE = """
🗂 Товар: <code>$title</code>
💶 Цена: <b>$price</b>
📍 Местоположение товара: <b>$location</b>
📖 Описание:
<code>$desc</code>

👁 Кол-во просмотров товара: <b>$views</b>
$delivery_more
🕒 Дата создания объявления: <b>$created_date</b>
🔗 <a href="$ad_link">Ссылка на товар</a>
🔗 <a href="$person_link">Ссылка на чат с продавцом</a>
🔗 <a href="$link_photo">Ссылка на фото</a>

🤵‍♂️ Имя продавца: <b>$person_name</b>
♂️ Гендер продавца: <b>$gender</b>
⭐️ Рейтинг продавца <b>$rating</b>
🕒 Дата регистрации продавца: <b>$person_reg_date</b>
📂 Кол-во объявления продавца: <b>$ads_number</b>
📧 Почта: <code>$email</code>
💬 Контакты: <code>$phone</code>
$social_block

👷‍♂️ Это объявление видело <b>$our_views</b> пользователей парсера
"""

STANDART_MSG_TEMPLATE = """📱<code>$title</code>
<b>🏷️ Цена:</b> <code>$price</code>
<b>📍 Местоположение:</b> <code>$location</code>
🔗 <a href="$link_photo">Фото товара</a>
🔗 <a href="$ad_link">Ссылка на товар</a>

<b>📖 Описание:</b>
<i>$desc</i>

<b>💼 Продавец:</b> <a href="$person_link">$person_name (Открыть чат)</a>
<b>🌟 Рейтинг:</b> <code>$rating</code>
<b>📧 Почта:</b> <code>$email</code>

<b>💬 Контакты:</b> <code>$phone</code>
$social_block
$delivery_more

<b>📝 Детали:</b>
• Дата регистрации продавца: <code>$person_reg_date</code>
• Объявление опубликовано: <code>$created_date</code>
• Объявлений от продавца: <code>$ads_number</code>
• Кол-во проданного товара: <code>$ads_number_selled</code>
• Кол-во купленного товара: <code>$ads_number_buyed</code>
• Просмотров: <code>$views</code>
• Гендер продавца: <code>$gender</code>

🕵️ Объявление просмотрело <code>$our_views</code> пользователей парсера
"""

MINIMALISTIC_TEMPLATE = """<code>$title</code> (<i>$desc</i>)
🔗 <a href="$link_photo">Фото товара</a>
🔗 <a href="$ad_link">Ссылка на товар</a>
<b>🏷️ Цена:</b> <code>$price</code>

<b>💼 Продавец:</b> <a href="$person_link">$person_name (Открыть чат)</a>
<b>📧 Почта:</b> <code>$email</code>
<b>💬 Контакты:</b> <code>$phone</code>
$social_block
Местоположение: 📍<code>$location</code>
$delivery

🕵️ Объявление просмотрело <code>$our_views</code> пользователей парсера
"""


def process_standard_template(template, parameters):
    # logger.debug(parameters)
    if not parameters.get("show_title", True):
        template = re.sub(r"📱<code>.*?</code>\n", "", template)
    if not parameters.get("show_price", True):
        template = re.sub(r"<b>🏷️ Цена:</b>.*?\n", "", template)
    if not parameters.get("show_location", True):
        template = re.sub(r"<b>📍 Местоположение:</b>.*?\n", "", template)
    if not parameters.get("show_desc", True):
        template = re.sub(
            r"<b>📖 Описание:</b>.*?<b>💼 Продавец:</b>",
            "<b>💼 Продавец:</b>",
            template,
            flags=re.DOTALL,
        )
    if not parameters.get("show_person_name", True):
        template = re.sub(r"<b>💼 Продавец:</b>.*?\n", "", template)
    if not parameters.get("show_rating", True):
        template = re.sub(r"<b>🌟 Рейтинг:</b>.*?\n", "", template)
    if not parameters.get("show_ads_number", True):
        template = re.sub(r"• Объявлений от продавца:.*?\n", "", template)
    if not parameters.get("show_ads_number", True):
        template = re.sub(r"• Кол-во проданного товара:.*?\n", "", template)
    if not parameters.get("show_ads_number", True):
        template = re.sub(r"• Кол-во купленного товара:.*?\n", "", template)
    if not parameters.get("show_ads_number_selled", True):
        template = re.sub(r"• Кол-во проданного товара:.*?\n", "", template)
    if not parameters.get("show_ads_number_buyed", True):
        template = re.sub(r"• Кол-во купленного товара:.*?\n", "", template)
    if not parameters.get("show_creation_date", True):
        template = re.sub(r"• Объявление опубликовано:.*?\n", "", template)
    if not parameters.get("show_views", True):
        template = re.sub(r"• Просмотров:.*?\n", "", template)
    if not parameters.get("show_person_joined", True):
        template = re.sub(r"• Дата регистрации продавца:.*?\n", "", template)
    if not parameters.get("show_delivery", True):
        template = re.sub(
            r"\$delivery_more.*?<b>📝 Детали:</b>",
            "<b>📝 Детали:</b>",
            template,
            flags=re.DOTALL,
        )
    if not parameters.get("show_email", True):
        template = re.sub(r"<b>📧 Почта:</b>.*?\n", "", template)
    if not parameters.get("show_gender", True):
        template = re.sub(r"• Гендер продавца:.*?\n", "", template)
    if not parameters.get("show_phone", True):
        template = re.sub(r"<b>💬 Контакты:</b>.*?\n", "", template)
    if not parameters.get("show_social_block", True):
        template = re.sub(r"\$social_block\n?", "", template)
    if not parameters.get("show_person_link", True):
        template = template.replace(" (Открыть чат)", "")

        def replacer(match):
            name = match.group(2)
            link = match.group(1)
            return (
                f"<b>💼 Продавец:</b> {name}"
                if link == "$person_link"
                else f"<b>💼 Продавец:</b> {name} ({link})"
            )

        template = re.sub(
            r'<b>💼 Продавец:</b> <a href="([^"]*)">([^<]+)</a>', replacer, template
        )

        template = re.sub(
            r'<b>💼 Продавец:</b> <a href="([^"]*)">([^<]+)</a>', replacer, template
        )

    if "<b>📝 Детали:</b>\n\n" in template:
        template = template.replace("<b>📝 Детали:</b>\n\n", "")

    return template


def process_minimalistic_template(template, parameters):
    if not parameters.get("show_desc", True):
        template = re.sub(r"\(.*?\)", "", template)
    if not parameters.get("show_title", True):
        # template = re.sub(r"<b>.*?</b> ", "", template)
        template = re.sub(r"<code>.*?</code>", "", template)
    if not parameters.get("show_price", True):
        template = re.sub(r"<b>🏷️ Цена:</b>.*?\n", "", template)
    if not parameters.get("show_location", True):
        template = re.sub(r"Местоположение: 📍.*?\n", "", template)
    if not parameters.get("show_person_name", True):
        template = re.sub(r"<b>💼 Продавец:</b>.*?\n", "", template)
    if not parameters.get("show_delivery", True):
        template = re.sub(r"\$delivery\n?", "", template)
    if not parameters.get("show_email", True):
        template = re.sub(r"<b>📧 Почта:</b>.*?\n", "", template)
    if not parameters.get("show_phone", True):
        template = re.sub(r"<b>💬 Контакты:</b>.*?\n", "", template)
    if not parameters.get("show_social_block", True):
        template = re.sub(r"\$social_block\n?", "", template)
    if not parameters.get("show_person_link", True):
        template = template.replace(" (Открыть чат)", "")

        def replacer(match):
            name = match.group(2)
            link = match.group(1)
            return (
                f"<b>💼 Продавец:</b> {name}"
                if link == "$person_link"
                else f"<b>💼 Продавец:</b> {name} ({link})"
            )

        template = re.sub(
            r'<b>💼 Продавец:</b> <a href="([^"]*)">([^<]+)</a>', replacer, template
        )

        template = re.sub(
            r'<b>💼 Продавец:</b> <a href="([^"]*)">([^<]+)</a>', replacer, template
        )

    return template


def process_old_template(template, parameters):
    # logger.debug(template)
    # Хитрый способ удаления заголовка, если он не нужен
    if not parameters.get("show_title", True):
        template = re.sub(r"🗂 Товар: <code>.*?</code>\n", "", template)

    # Удаляем строку с ценой, если нужно
    if not parameters.get("show_price", True):
        template = re.sub(r"💶 Цена: <b>.*?</b>\n", "", template)

    # Удаляем строку с местоположением, если нужно
    if not parameters.get("show_location", True):
        template = re.sub(r"📍 Местоположение товара: <b>.*?</b>\n", "", template)

    # И так далее...
    if not parameters.get("show_desc", True):
        template = re.sub(
            r"📖 Описание:\n<code>.*?</code>\n", "", template, flags=re.DOTALL
        )

    if not parameters.get("show_creation_date", True):
        template = re.sub(r"🕒 Дата создания объявления: <b>.*?</b>\n", "", template)

    if not parameters.get("show_gender", True):
        template = re.sub(r"♂️ Гендер продавца: <b>.*?\n", "", template)

    if not parameters.get("show_ad_link", True):
        template = re.sub(
            r"🔗 <a href=\"\$ad_link\">Ссылка на товар</a>\n", "", template
        )

    if not parameters.get("show_views", True):
        template = re.sub(r"👁 Кол-во просмотров товара: <b>.*?</b>\n", "", template)

    if not parameters.get("show_rating", True):
        template = re.sub(r"⭐️ Рейтинг продавца <b>.*?</b>\n", "", template)

    if not parameters.get("show_person_link", True):
        template = re.sub(
            r"🔗 <a href=\"\$person_link\">Ссылка на чат с продавцом</a>\n", "", template
        )

    if not parameters.get("show_link_photo", True):
        template = re.sub(
            r"🔗 <a href=\"\$link_photo\">Ссылка на фото</a>\n", "", template
        )

    if not parameters.get("show_person_name", True):
        template = re.sub(r"🤵‍♂️ Имя продавца: <b>.*?</b>\n", "", template)

    if not parameters.get("show_person_joined", True):
        template = re.sub(r"🕒 Дата регистрации продавца: <b>.*?</b>\n", "", template)

    if not parameters.get("show_ads_number", True):
        template = re.sub(r"📂 Кол-во объявления продавца: <b>.*?</b>\n", "", template)

    if not parameters.get("show_email", True):
        template = re.sub(r"📧 Почта: <code>.*?</code>\n", "", template)

    if not parameters.get("show_phone", True):
        template = re.sub(r"💬 Контакты: <code>.*?</code>\n", "", template)
    if not parameters.get("show_social_block", True):
        template = re.sub(r"\$social_block\n?", "", template)

    if not parameters.get("show_delivery", True):
        template = re.sub(r"\$delivery_more\n?", "", template)

    return template


async def manipulate_msg_template(parameters=None, user_id=None, data=None):
    if parameters is None:
        try:
            parameters = await db.get_configuration_settings(user_id=user_id)
            parameters = parameters[0]
        except IndexError:
            logger.debug(traceback.format_exc())
            return ""

    if not data:
        if parameters.get("style") == 2:
            social_block = """\n✅WhatsApp:
<a href="https://www.google.com/">📱</a>/<a href="https://www.google.com/">🖥</a>

Viber: <a href="https://www.google.com/">📱</a>
Telegram: <a href="https://www.google.com/">📱</a>"""
        else:
            social_block = """• WhatsApp ✅: <a href="https://www.google.com/">📱</a>/<a href="https://www.google.com/">🖥</a>
• Viber: <a href="https://www.google.com/">📱</a>
• Telegram: <a href="https://www.google.com/">📱</a>"""

        data = {
            "$title": "Айфон 7 32гб",
            "$desc": "Продам айфон 7 32 Гб 88 % батарея стан",
            "$ad_link": "https://www.google.com/ad",
            "$link_photo": "https://www.google.com/photo",
            "$price": "2 200 грн.",
            "$person_name": "Микола К",
            "$person_link": "https://www.google.com/person",
            "$email": "fsdfdsf@gmail.com",
            "$phone": "+41693257315",
            "$created_date": "5 минут назад",
            "$person_reg_date": "10 месяцев 14 дней 3 часа  назад",
            "$ads_number_buyed": "2",
            "$ads_number_selled": "1",
            "$ads_number": "3",
            "$location": "Berlin",
            "$our_views": "0",
            "$views": "10",
            "$gender": "Мужской",
            "$rating": "1",
            "$delivery_more": """<b>📦 Доставка:</b>
• Доставка через OLX доступна
• Успешных доставок: <code>100</code>""",
            "$delivery": "📦 Доставка доступна",
            "$social_block": social_block,
        }

    parameters = dict(parameters)
    for key, value in data.items():
        if value is None or value == "":
            param_key = f"show_{key[1:]}"
            parameters[param_key] = False

    template = (
        {
            0: process_standard_template(STANDART_MSG_TEMPLATE, parameters),
            1: process_minimalistic_template(MINIMALISTIC_TEMPLATE, parameters),
            2: process_old_template(OLD_TEMPLATE, parameters),
        }
        .get(parameters.get("style"))
        .replace("<code><code>", "<code>")
        .replace("</code></code>", "</code>")
    )
    # logger.debug(template)

    if parameters.get("compact_view"):
        template = template.replace("\n\n", "\n")

    for key, value in data.items():
        if value is not None:
            template = template.replace(key, str(value))

    return template


async def get_visibility_setting_menu_param(user_id):
    state_data = await redis.hgetall(f"user_settings:{user_id}")
    if state_data:
        state_data = {
            k.decode("utf-8"): ujson.loads(v.decode("utf-8"))
            for k, v in state_data.items()
        }

    return state_data
