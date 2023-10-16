import asyncio
import traceback
import warnings
from contextlib import suppress
from pathlib import Path

import sentry_sdk
import ujson
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand
from loguru import logger
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from . import dp, config, handlers, db, redis, bot, scheduler_, worker
from .config import PROD
from .handlers.start_parsing import run_parser
from .keyboards.site_actions import stop_parser
from .misc.parser_essintials import (
    pool_process,
    wrapper_for_run_cpu_bound,
)
from .misc.scheduler import run_scheduler_jobs


async def setup_default_commands(bot):
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="▶️ Начать работу с ботом"),
            BotCommand(command="timezone", description="🌍 Выбрать часовой пояс"),
            BotCommand(
                command="stop_msg", description="❌ Остановить отправку сообщений"
            ),
        ]
    )
    logger.info("Standard commands are successfully configured")


async def notify_admins(admins, bot):
    count = 0

    for admin in admins:
        with suppress(TelegramAPIError):
            await bot.send_message(admin, "Бот Запущен!")
            count += 1

    logger.info(f"{count} admins received messages")


async def rerun_activity_parsing():
    get_active_parsing = await db.get_running_parser_recovery_info()
    logger.debug(f"restarting {len(get_active_parsing)} parsers")
    # return
    if get_active_parsing:
        for row in get_active_parsing:
            parser_str = row.get("info")

            parser = ujson.loads(parser_str)
            user_id = parser.get("user_id")
            stat_id = parser.get("stat_id")
            parser["rerun"] = True

            with suppress(Exception):
                await bot.send_message(
                    user_id,
                    text=f"🔄 Бот был перезапущен, перезапускаю ваш парсинг #{stat_id}...",
                    reply_markup=stop_parser,
                )

            await db.update_date_stats_ticker(user_id, stat_id)

            # asyncio.get_running_loop().run_in_executor(
            #     pool_process,
            #     wrapper_for_run_cpu_bound,
            #     run_parser,
            #     parser,
            # )
            asyncio.create_task(run_parser(parser))
            # asyncio.create_task(worker.process_pool.submit(run_parser, parser))

            await asyncio.sleep(1)


async def on_startup(bot: Bot):
    loop = asyncio.get_running_loop()

    if PROD:
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        warnings.filterwarnings("ignore", category=PendingDeprecationWarning)

    loop.slow_callback_duration = 0.800

    # sentry_sdk.init(
    #     dsn="https://1",
    #     integrations=[AioHttpIntegration()],
    #     traces_sample_rate=1.0,
    #     profiles_sample_rate=1.0,
    # )

    logdir = Path(config.LOG_DIR)
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir.joinpath("tgbot.log")
    logger.add(logfile, rotation="1 day", retention="1 week")

    asyncio.create_task(notify_admins(config.ADMINS, bot))
    asyncio.create_task(setup_default_commands(bot))

    await db.create()

    asyncio.create_task(rerun_activity_parsing())

    scheduler_.start()
    logger.debug("scheduler started")

    if not PROD:
        await db.create_table_tickets()
        await db.create_table_stats_ticker()
        await db.create_table_run_stats()
        await db.create_table_user_parser_status()
        await db.create_table_proxy_manager_blacklist()
        await db.create_table_running_parser_recovery_info()
        await db.create_table_throttling_control_proxy()
        await db.create_table_parser_history()
        await db.create_table_parser_stats_history()
        await db.create_table_user_saved_links()
        await db.create_table_custom_msg_text()
        await db.create_table_worker_views()
        await db.create_table_user_word_complete()
        await db.create_table_payments_stats()
        await db.create_table_subscription_change_history()
        await db.create_table_blacklist_persons()
        await db.create_table_user_presets()
        await db.create_table_wa_credits()
        await db.create_table_site_features()
        await db.create_table_blacklisted_words()
        await db.create_table_bot_users()
        await db.create_table_payment_info()
        await db.create_table_user_tokens()
        await db.create_table_subscriptions_sites()
        await db.create_table_site_status()
        await db.create_table_user_settings()

    asyncio.create_task(run_scheduler_jobs())
    # asyncio.create_task(send_msg_after_find())
