import asyncio

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import UNHANDLED
from loguru import logger


class LoggerMiddleware(BaseMiddleware):
    async def __call__(self, handler, update, data):
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        handled = False
        try:
            result = await handler(update, data)
            handled = result is not UNHANDLED
            return result
        finally:
            duration = (loop.time() - start_time) * 1000
            if duration > 1500:
                logger.info(
                    f"Update {update} is {'handled' if handled else 'not handled'}. Duration {duration} ms by bot id={data['bot'].id}",
                )
