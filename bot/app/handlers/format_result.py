import asyncio
import csv
import html
import random
import re
import traceback
import uuid
from contextlib import suppress
from datetime import datetime
from io import StringIO, BytesIO

import aiohttp
import ujson
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    BufferedInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiohttp import ClientTimeout, TCPConnector
from bs4 import BeautifulSoup, NavigableString, Tag
from loguru import logger
from openpyxl.workbook import Workbook
from telegraph.aio import Telegraph

from app import dp, db, worker
from app.config import SENDER_STATUS_DB
from app.keyboards.start_menu_markup import get_start_menu_markup
from app.misc.msg_templates_manipulator import manipulate_msg_template
from app.misc.notify import send_document
from app.misc.parser_essintials import (
    handle_ticker,
    pool_process,
    wrapper_for_run_cpu_bound,
)
from app.misc.time_declension import humanize_date

router = Router()
dp.include_router(router)


def remove_html_tags(input_str: str) -> str:
    # Извлекаем все пары (ссылка, текст)
    links = re.findall(r'<a href="([^"]+)">([^<]+)</a>', input_str)

    # Убираем все HTML-теги
    clean_text = re.sub(r"<[^>]*>", "", input_str)

    # Заменяем текст ссылки на формат "Текст (ссылка)"
    for link, text in links:
        clean_text = clean_text.replace(text, f"{text} ({link})")

    return clean_text


async def write_data_to_memory(row, user_id):
    if row.get("phone") and row.get("phone") != '""':
        phone_block = ujson.loads(row.get("phone"))
        phone = "".join(phone_block.get("contact_text"))
        social_block = phone_block.get("all_texts")
        # logger.debug(social_block)
    else:
        phone = None
        social_block = None

    if row.get("possible_phones") and not row.get("phone"):
        phone = ";".join(ujson.loads(row.get("possible_phones")))
    # if not phone:
    # logger.debug(phone_block)
    data = {
        "$title": row.get("title"),
        "$desc": html.escape(row.get("description")),
        "$ad_link": row.get("ad_link"),
        "$link_photo": row.get("photo"),
        "$price": row.get("price"),
        "$person_name": row.get("person_name"),
        "$person_link": row.get("person_link"),
        "$created_date": humanize_date(row.get("creation_date")),
        "$person_reg_date": humanize_date(row.get("person_registration_date")),
        "$ads_number_buyed": row.get("ads_number_buyed"),
        "$ads_number_selled": row.get("ads_number_selled"),
        "$ads_number": row.get("ads_number"),
        "$location": row.get("location"),
        "$our_views": row.get("our_views"),
        "$phone": phone,
        "$social_block": social_block,
        "$views": row.get("views"),
        "$rating": row.get("rating"),
        "$gender": row.get("gender"),
        "$email": row.get("email"),
        "$delivery_more": """<b>📦 Доставка:</b>
• $delivery_no_emodji
• Успешных доставок: <code>$success_delivery_count</code>""",
        "$delivery_no_emodji": "Доставка доступна"
        if row.get("delivery") != "N/A"
        else None,
        "$success_delivery_count": row.get("success_delivery_count"),
        "$delivery": "📦 Доставка доступна" if row.get("delivery") != "N/A" else None,
    }
    template = await manipulate_msg_template(user_id=user_id, data=data)
    if "$success_delivery_count" in template:
        template = re.sub(r"• Успешных доставок:.*?\n", "", template)

    return template, data


async def write_vcf(in_memory_file, history, user_id):
    for row in history:
        template, data = await write_data_to_memory(row, user_id)
        item_title = data.get("$title")
        item_link = data.get("$ad_link")
        item_phone = data.get("$phone")
        if item_phone is None:
            item_phone = ""

        in_memory_file.write(
            f"""BEGIN:VCARD
N:{item_title}
TEL;CELL:{item_phone.split('; ')[0]}
NOTE: {item_link}
END:VCARD""".encode(
                "utf-8"
            )
        )


async def write_csv(stat_id, history, user_id):
    in_memory_file = BytesIO()
    # await db.create(max_size=3, min_size=1)
    # history = await db.get_user_parser_history(stat_id=stat_id, user_id=user_id)
    if not history:
        # await db.close()
        return

    header_mapping = {
        "$title": "Название",
        "$desc": "Описание",
        "$ad_link": "Ссылка на объявление",
        "$link_photo": "Ссылка на фото",
        "$price": "Цена",
        "$person_name": "Имя продавца",
        "$person_link": "Ссылка на чат с продавцом",
        "$created_date": "Дата создания",
        "$person_reg_date": "Дата регистрации продавца",
        "$ads_number_buyed": "Количество купленных объявлений",
        "$ads_number_selled": "Количество проданных объявлений",
        "$ads_number": "Общее количество объявлений",
        "$location": "Местоположение",
        "$our_views": "Кол-во просмотров от наших пользователей",
        "$phone": "Телефон",
        "$views": "Просмотры",
        "$rating": "Рейтинг",
        "$email": "Эл. почта",
        "$gender": "Гендер",
        "$delivery": "Доставка",
    }

    _, first_row_data = await write_data_to_memory(history[0], user_id)
    headers = [header_mapping.get(k, k) for k in first_row_data.keys()]
    headers = [header for header in headers if not header.startswith("$")]

    string_buffer = StringIO()
    # writer = csv.DictWriter(string_buffer, fieldnames=headers)
    writer = csv.DictWriter(string_buffer, fieldnames=headers, delimiter=",")
    writer.writeheader()

    for row in history:
        _, data = await write_data_to_memory(row, user_id)
        renamed_data = {
            header_mapping.get(k, k): str(v) if v else "" for k, v in data.items()
        }
        renamed_data.pop("$delivery_more")
        renamed_data.pop("$delivery_no_emodji")
        renamed_data.pop("$success_delivery_count")
        renamed_data.pop("$social_block")

        if renamed_data.get("Телефон"):
            renamed_data["Телефон"] = remove_html_tags(renamed_data["Телефон"])

        # logger.debug(renamed_data)
        writer.writerow(renamed_data)

    csv_data = string_buffer.getvalue()
    in_memory_file.write("\ufeff".encode("utf-8"))
    in_memory_file.write(csv_data.encode("utf-8"))
    # await db.close()

    in_memory_file.seek(0)
    async with aiohttp.ClientSession(
            json_serialize=ujson.dumps,
            timeout=ClientTimeout(total=20),
            connector=TCPConnector(limit_per_host=10_000, limit=10_000),
    ) as sess:
        await send_document(
            chat_id=user_id,
            sess=sess,
            file_bytes=in_memory_file,
            filename=f'parser-result {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.csv',
        )


async def write_txt(in_memory_file, history, user_id):
    for row in history:
        template, _ = await write_data_to_memory(row, user_id)
        in_memory_file.write(
            remove_html_tags(template + "=" * 50 + "\n").encode("utf-8")
        )


async def write_txt_list(in_memory_file, history, user_id):
    for row in history:
        _, data = await write_data_to_memory(row, user_id)
        link = data.get("$ad_link")
        in_memory_file.write(f"{link}\n".encode("utf-8"))


async def write_sender(in_memory_file, history, user_id):
    json_data = {"items": []}
    for row in history:
        template, data = await write_data_to_memory(row, user_id)

        item_title = data.get("$title")
        item_link = data.get("$ad_link")
        item_price = data.get("$price")
        item_person_name = data.get("$person_name")

        json_data["items"].append(
            {
                "item_title": item_title,
                "item_price": item_price,
                "item_link": item_link,
                "item_person_name": item_person_name,
            }
        )

    json_data = ujson.dumps(json_data)
    in_memory_file.write(json_data.encode("utf-8"))


HTML_TEMPLATE = """
<html>
<head>
    <meta charset="UTF-8">
<style>
    body {
        background-color: #222222;
        font-family: 'Arial', sans-serif;
        color: #E5E5E5;
        text-align: center;  /* Центрируем все карточки на странице */
    }
    .card {
        border: 1px solid #444;
        margin: 10px auto;  /* Центрирование и отступы */
        padding: 10px;
        border-radius: 5px;
        display: inline-block;  
        max-width: 800px;  /* Максимальная ширина */
    }
    img {
        max-width: 400px;  /* Увеличиваем фото */
        margin: 0 auto;  /* Центрируем фото */
        margin-top: 10px;  /* Отступ сверху */
        margin-bottom: 30px;  /* Отступ сверху */
    }
    .content {
        white-space: pre-line;
        font-size: 18px;  /* Увеличиваем размер шрифта */
        text-align: left;  /* Выравниваем текст по левому краю */
        margin-top: 10px;  /* Отступ сверху */
    }
    a:link {
        color: #FFA500;
    }
    a:visited {
        color: #FFA500;
    }
</style>


</head>
<body>
    <div class="card">
        <img src="$link_photo" />
        <div class="content">$custom_template</div>
    </div>
</body>
</html>
"""


async def write_html(in_memory_file, history, user_id):
    in_memory_file.write(
        '<html><head><meta charset="UTF-8"></head><body>'.encode("utf-8")
    )

    for row in history:
        template, data = await write_data_to_memory(row, user_id)

        html_block = HTML_TEMPLATE.replace("$custom_template", template)
        for key, value in data.items():
            html_block = html_block.replace(key, str(value) if value else "")

        in_memory_file.write(html_block.encode("utf-8"))

    in_memory_file.write("</body></html>".encode("utf-8"))


def split_html_message(html: str, max_length: int = 1012):
    soup = BeautifulSoup(html, "html.parser")

    chunks = []

    current_chunk = []

    current_length = 0

    open_tags = []

    for element in soup:
        if isinstance(element, NavigableString):
            text = str(element)

            text_length = len(text)

            if current_length + text_length > max_length:
                remaining_space = max_length - current_length

                current_chunk.append(text[:remaining_space])

                chunks.append("".join(current_chunk))

                # Reset current_chunk and add remaining text

                current_chunk = [text[remaining_space:]]

                current_length = text_length - remaining_space

                # Re-open any tags that were open

                for tag in open_tags:
                    current_chunk.insert(0, f"<{tag}>")

                    current_length += len(tag) + 2

            else:
                current_chunk.append(text)

                current_length += text_length

        elif isinstance(element, Tag):
            if element.is_empty_element:
                current_chunk.append(str(element))

                current_length += len(str(element))

            else:
                for sub_element in element.contents:
                    if isinstance(sub_element, NavigableString):
                        text = str(sub_element)

                        text_length = len(text)

                        if current_length + text_length > max_length:
                            remaining_space = max_length - current_length

                            current_chunk.append(text[:remaining_space])

                            chunks.append("".join(current_chunk))

                            # Reset current_chunk and add remaining text

                            current_chunk = [text[remaining_space:]]

                            current_length = text_length - remaining_space

                            # Re-open any tags that were open

                            for tag in open_tags:
                                current_chunk.insert(0, f"<{tag}>")

                                current_length += len(tag) + 2

                        else:
                            current_chunk.append(text)

                            current_length += text_length

                        # Add open and close tag around the text

                        current_chunk[
                            -1
                        ] = f"<{element.name}>{current_chunk[-1]}</{element.name}>"

                        current_length += len(element.name) * 2 + 5

                    else:
                        current_chunk.append(str(sub_element))

                        current_length += len(str(sub_element))

                # Remember open tags

                if element.name not in ["br", "hr", "img"]:
                    open_tags.append(element.name)

    # Add remaining chunk if any

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


async def write_msg(bot, history, user_id, send_msg=False):
    SENDER_STATUS_DB[str(user_id)] = "work"

    if SENDER_STATUS_DB.get(str(user_id)) == "stop":
        return

    configuration_settings = await db.get_configuration_settings(user_id=int(user_id))
    if configuration_settings is None:
        await bot.send_message(
            text="❌ Пропишите /start и попробуй заново", chat_id=user_id
        )
        return
    configuration_settings = configuration_settings[0]

    for row in history:
        try:
            if SENDER_STATUS_DB[str(user_id)] == "stop":
                break

            template, data = await write_data_to_memory(row, user_id)
            # logger.debug(len(template))
            if data.get("$link_photo") and configuration_settings.get("show_photo"):
                if 2400 < len(template) < 4096:
                    await bot.send_message(text=template, chat_id=user_id)
                elif len(template) > 4096:
                    for x in range(0, len(template), 4096):
                        await bot.send_message(
                            text=remove_html_tags(template[x: x + 4096]),
                            chat_id=user_id,
                        )
                else:
                    try:
                        await bot.send_photo(
                            chat_id=user_id,
                            caption=template,
                            photo=data.get("$link_photo"),
                        )
                    except TelegramForbiddenError:
                        SENDER_STATUS_DB[str(user_id)] = "stop"
                    except Exception:
                        logger.debug(traceback.format_exc())
                        logger.debug(data.get("$link_photo"))
                        try:
                            await bot.send_message(text=template, chat_id=user_id)
                        except Exception:
                            logger.debug(traceback.format_exc())
                            logger.debug(template)
            else:
                await bot.send_message(text=template, chat_id=user_id)
        except TelegramForbiddenError:
            SENDER_STATUS_DB[str(user_id)] = "stop"
        except Exception:
            logger.debug(traceback.format_exc())
            logger.debug(template)

        await asyncio.sleep(random.uniform(1.2, 3.5))

    if send_msg:
        await bot.send_message(
            chat_id=user_id,
            text="✅ Вы получили все сообщения",
            reply_markup=get_start_menu_markup(user_id),
        )


async def write_to_telegraph(history, user_id, query):
    MAX_SIZE = 30000  # 34k символов
    try:
        telegraph = Telegraph()
        await telegraph.create_account(
            short_name="1",
            author_name="1 Parser",
            author_url="https://t.me/@1",
        )
    except Exception:
        logger.debug(traceback.format_exc())
        await query.message.answer("❌ Что-то пошло не так, попробуйте еще раз")
        return
    current_size = 0
    html_content = ""
    pages = []

    async def send_chunk_to_telegraph(content, counter):
        nonlocal pages  # чтобы работать с внешней переменной pages
        response = await telegraph.create_page(
            title=f"Экспорт {str(uuid.uuid4()).replace('-', '')} (Часть {counter})",
            html_content=content,
        )
        pages.append(f"https://telegra.ph/{response['path']}")

    counter = 1
    for row in history:
        template, data = await write_data_to_memory(row, user_id)
        new_entry = ""

        if data.get("$link_photo"):
            new_entry += f"<img src='{data.get('$link_photo')}' alt='photo'/>"

        new_entry += f"<pre>{template}</pre>"
        new_entry_size = len(new_entry)

        if current_size + new_entry_size >= MAX_SIZE:
            await send_chunk_to_telegraph(html_content, counter)
            html_content = ""
            current_size = 0
            counter += 1

        html_content += new_entry
        current_size += new_entry_size

    if html_content:  # если что-то осталось
        await send_chunk_to_telegraph(html_content, counter)

    await query.message.answer(
        "⚠️ Для просмотра лучше использовать предпросмотр в телеграме\n\nВаши ссылки:\n"
        + "\n\n".join(pages)
    )


# async def write_to_telegraph(history, user_id, query):
#     telegraph = Telegraph()
#     await telegraph.create_account(
#         short_name="1",
#         author_name="1 1",
#         author_url="https://t.me/@1",
#     )
#
#     CHUNK_SIZE = (
#         20  # Количество записей на одну страницу. Подбери это число под свои нужды.
#     )
#     pages = []
#
#     for i in range(0, len(history), CHUNK_SIZE):
#         chunk = history[i : i + CHUNK_SIZE]
#
#         html_content = ""
#         for row in chunk:
#             template, data = await write_data_to_memory(row, user_id)
#
#             if data.get("$link_photo"):
#                 html_content += f"<img src='{data.get('$link_photo')}' alt='photo'/>"
#
#             html_content += f"<pre>{template}</pre>"
#             # html_content += '-' * 80
#             # html_content += f"{template}"
#
#         response = await telegraph.create_page(
#             title=f"Экспорт {str(uuid.uuid4()).replace('-', '')} (Часть {i // CHUNK_SIZE + 1})",
#             html_content=html_content,
#         )
#         pages.append(f"https://telegra.ph/{response['path']}")
#
#     # return pages
#     # del telegraph
#     await query.message.answer(
#         "⚠️ Для просмотра лучше использовать предпросмотр в телеграме\n\nВаши ссылки:\n"
#         + "\n\n".join(pages)
#     )


flags = {"throttling_key": "format_result"}


def get_column_letter(col_num):
    letters = ""
    while col_num:
        mod = (col_num - 1) % 26
        letters += chr(mod + 65)
        col_num = (col_num - 1) // 26
    return "".join(reversed(letters))


async def write_xlsx(stat_id, history, user_id):
    # await db.create(max_size=3, min_size=1)
    # history = await db.get_user_parser_history(stat_id=stat_id, user_id=user_id)
    if not history:
        # await db.close()
        return

    # То же отображение заголовков
    header_mapping = {
        "$title": "Название",
        "$desc": "Описание",
        "$ad_link": "Ссылка на объявление",
        "$link_photo": "Ссылка на фото",
        "$price": "Цена",
        "$person_name": "Имя продавца",
        "$person_link": "Ссылка на чат с продавцом",
        "$created_date": "Дата создания",
        "$person_reg_date": "Дата регистрации продавца",
        "$ads_number_buyed": "Количество купленных объявлений",
        "$ads_number_selled": "Количество проданных объявлений",
        "$ads_number": "Общее количество объявлений",
        "$location": "Местоположение",
        "$our_views": "Кол-во просмотров от наших пользователей",
        "$phone": "Телефон",
        "$views": "Просмотры",
        "$rating": "Рейтинг",
        "$gender": "Гендер продавца",
        "$email": "Эл. почта",
        "$delivery": "Доставка",
    }

    _, first_row_data = await write_data_to_memory(history[0], user_id)
    headers = [header_mapping.get(k, k) for k in first_row_data.keys()]
    headers = [header for header in headers if not header.startswith("$")]

    wb = Workbook()
    ws = wb.active

    # Записываем заголовки
    for col_num, header in enumerate(headers, 1):
        col_letter = get_column_letter(col_num)
        ws[f"{col_letter}1"] = header

    # Записываем данные
    for row_num, row in enumerate(history, 2):
        _, data = await write_data_to_memory(row, user_id)
        renamed_data = {
            header_mapping.get(k, k): str(v) if v else "" for k, v in data.items()
        }

        if renamed_data.get("Телефон"):
            renamed_data["Телефон"] = remove_html_tags(renamed_data["Телефон"])

        for col_num, header in enumerate(headers, 1):
            ws.cell(row=row_num, column=col_num, value=renamed_data.get(header, ""))

    # await db.close()

    # Сохраняем в памяти
    in_memory_file = BytesIO()
    wb.save(in_memory_file)
    in_memory_file.seek(0)

    # Отправляем файл
    async with aiohttp.ClientSession(
            json_serialize=ujson.dumps,
            timeout=ClientTimeout(total=20),
            connector=TCPConnector(limit_per_host=10_000, limit=10_000),
    ) as sess:
        await send_document(
            chat_id=user_id,
            sess=sess,
            file_bytes=in_memory_file,
            filename=f'parser-result {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.xlsx',
        )


@router.callback_query(F.data.contains("format_result"), flags=flags)
async def format_result(query: CallbackQuery):
    stat_id = int(query.data.split("|")[-2])
    format = query.data.split("|")[-1].casefold()
    # logger.debug(format)

    history = await db.get_user_parser_history(
        stat_id=stat_id, user_id=query.from_user.id
    )
    if not history:
        await query.message.answer("❌ Ни один товар не был найден")
        return

    in_memory_file = BytesIO()
    if format == "txt":
        await write_txt(in_memory_file, history, query.from_user.id)
    elif format == "list_txt":
        await write_txt_list(in_memory_file, history, query.from_user.id)
    elif format == "html":
        await write_html(in_memory_file, history, query.from_user.id)
    elif format == "vcf":
        await write_vcf(in_memory_file, history, query.from_user.id)
    elif format == "csv":
        # await write_csv(in_memory_file, history, query.from_user.id)
        # asyncio.get_running_loop().run_in_executor(
        #     pool_process,
        #     wrapper_for_run_cpu_bound,
        #     write_csv,
        #     stat_id,
        #     query.from_user.id,
        # )
        await write_csv(stat_id, history, query.from_user.id)
        # asyncio.create_task(
        #     worker.process_pool.submit(write_csv, stat_id, query.from_user.id)
        # )
        return
    elif format == "xlsx":
        await write_xlsx(in_memory_file, history, query.from_user.id)
        # asyncio.get_running_loop().run_in_executor(
        #     pool_process,
        #     wrapper_for_run_cpu_bound,
        #     write_xlsx,
        #     stat_id,
        #     query.from_user.id,
        # )
        # asyncio.create_task(
        #     worker.process_pool.submit(write_xlsx, stat_id, query.from_user.id)
        # )
        return
    elif format == "msg":
        await query.message.answer(
            ".",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [
                        KeyboardButton(
                            text="❌ Остановить отправку сообщений.",
                        )
                    ],
                ],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        asyncio.create_task(
            write_msg(query.bot, history, query.from_user.id, send_msg=True)
        )
        return
    elif format == "telegraph":
        asyncio.create_task(write_to_telegraph(history, query.from_user.id, query))
        return
    elif format == "sender":
        await write_sender(in_memory_file, history, query.from_user.id)

    if format == "list_txt":
        format = "txt"

    in_memory_file.seek(0)
    await query.message.answer_document(
        document=BufferedInputFile(
            in_memory_file.read(),
            filename=f'parser-result {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.{format}',
        )
    )


async def renew_stats(stat_id, chat_id):
    # await db.create(max_size=3, min_size=1)

    ticker = await db.get_all_stats_id_by_user_id(chat_id, stat_id)
    # logger.debug(ticker)

    if ticker:
        ticker = ticker[0]

        async with aiohttp.ClientSession(
                json_serialize=ujson.dumps,
                timeout=ClientTimeout(total=20),
                connector=TCPConnector(limit_per_host=10_000, limit=10_000),
        ) as sess:
            await handle_ticker(ticker, "no_dp", edit_time=False, sess=sess)

    # await db.close()


@router.callback_query(F.data.contains("renew_stats"), flags=flags)
async def renew_stats_handler(query: CallbackQuery):
    stat_id = int(query.data.split("|")[-1])

    # await worker.process_pool.submit(renew_stats, stat_id, query.from_user.id)
    asyncio.create_task(renew_stats(stat_id, query.from_user.id))

    with suppress(TelegramAPIError):
        await query.answer()
