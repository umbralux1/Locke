from typing import Any, Dict, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.dispatcher.flags import get_flag
from aiogram.types import Message, CallbackQuery
from cachetools import Cache
from time import time

from loguru import logger


class ThrottlingCache(Cache):
    def __init__(self, maxsize, ttl, limit):
        super().__init__(maxsize)
        self.ttl = ttl
        self.limit = limit
        self.data = {}

    def __getitem__(self, key):
        item = self.data.get(key)
        return item["count"] if item and time() - item["time"] < self.ttl else 0

    def __setitem__(self, key, value):
        self.data[key] = {"count": value, "time": time()}

    def __contains__(self, key):
        if key in self.data:
            if time() - self.data[key]["time"] < self.ttl:
                return True
            else:
                del self.data[key]
        return False

    def add(self, key):
        if key in self:
            self.data[key]["count"] += 1
            if self.data[key]["count"] >= self.limit:
                return True
        else:
            self.data[key] = {"count": 1, "time": time()}
        return False


class ThrottlingMiddleware(BaseMiddleware):
    caches = {
        "format_result": ThrottlingCache(maxsize=10_000, ttl=2, limit=3),
        "anypay_check": ThrottlingCache(maxsize=10_000, ttl=2, limit=3),
        "payok_check": ThrottlingCache(maxsize=10_000, ttl=2, limit=3),
        "crypto_bot_check": ThrottlingCache(maxsize=10_000, ttl=2, limit=3),
        "default": ThrottlingCache(maxsize=10_000, ttl=5, limit=3),
    }

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        throttling_key = get_flag(data, "throttling_key")
        user_id = event.from_user.id

        if (
            throttling_key
            and throttling_key in self.caches
            and self.caches[throttling_key].add(user_id)
        ):
            if isinstance(event, CallbackQuery):
                await event.message.reply("Слишком много запросов, перестань флудить!")
            else:
                await event.reply("Слишком много запросов, перестань флудить!")
            logger.debug(f"throttled {throttling_key} request {user_id}")
            return

        return await handler(event, data)
