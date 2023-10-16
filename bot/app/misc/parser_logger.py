import traceback

from loguru import logger

from app.keyboards.all_sites_menu import make_place_pretty_view
from app.misc.parser_essintials import decode_and_split_urls


async def log_parser_run_for_admin(msg, site, state, stat_id):
    #     await msg.bot.send_message(
    #         chat_id=CHATS.get("activity"),
    #         text=f"""
    # #{stat_id}
    # Парсер запущен !
    #
    # Сайт: {make_place_pretty_view(site)}
    #
    # Пользователь: {msg.from_user.mention_html()}/Username-{msg.chat.username}/ID-{msg.chat.id}
    # State: {state}
    # """,
    #     )
    text = f"""
#{stat_id}
Парсер запущен !

Сайт: {make_place_pretty_view(site)}

Пользователь: {msg.from_user.mention_html()}/Username-{msg.chat.username}/ID-{msg.chat.id}
State: {state}
        """
    # logger.debug(text)


async def send_update_get_items(pool_urls, stat_id):
    try:
        push_text = (
            f"Обновление по #{stat_id}\n\nинтерпретирование пар"
            f"сером ссылки\n\n{decode_and_split_urls(pool_urls)}"
        )
        # await send_large_text(
        #     chat_id=CHATS.get("activity"),
        #     text=push_text,
        #     semaphore=semaphore_logs_send,
        # )
        # logger.debug(push_text)
    except Exception:
        logger.debug(traceback.format_exc())
