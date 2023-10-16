import asyncio
import random
import traceback

from loguru import logger

from app import db
from app.proxys import (
    PROXY_ANIBIS,
    PROXY_WILLHABEN,
)


class NoProxy(Exception):
    ...


class AllProxyBlacklisted(Exception):
    ...


class ProxyManager:
    GROUND_PROXY_MAP = {
        "anibis": PROXY_ANIBIS,
        "willhaben": PROXY_WILLHABEN,
    }
    GROUND_PROXY_DEFAULT = ()
    PROXY_BLACKLIST_KEY = "proxy_manager_blacklist"

    async def get_proxy(self, ground="all", redis_=None, in_use_proxy=None):
        proxy_pool = self._get_proxies(ground)

        if not proxy_pool:
            logger.error(f'no proxy found for ground "{ground}"')
            raise NoProxy(f'no proxy found for ground "{ground}"')

        # Get random proxy from the list that is not in blacklist:
        random.shuffle(proxy_pool)
        try:
            bl = await self.get_proxy_blacklist(redis_)
        except asyncio.CancelledError:
            raise

        if in_use_proxy:
            proxy_pool = list(set(proxy_pool) - set(in_use_proxy))

        random.shuffle(proxy_pool)
        while proxy_pool:
            proxy = proxy_pool.pop()

            if proxy not in bl:
                break
        else:
            logger.error(f'all proxies for ground "{ground}" blacklisted')
            raise AllProxyBlacklisted(f'all proxies for ground "{ground}" blacklisted')

        # logger.debug(proxy)
        return f"http://{proxy}"

    async def blacklist_proxy(self, proxy, redis_):
        logger.debug(f"blacklist proxy: {proxy}")
        try:
            await db.add_blacklist_proxy(proxy)
        except Exception:
            ...

    async def enable_proxy(self, proxy, redis_):
        # logger.debug(f"enable proxy: {proxy}")
        await db.remove_blacklist_proxy(proxy)

    async def get_proxy_blacklist(self, redis_):
        try:
            return await db.get_blacklist_proxy() or set()
        except asyncio.CancelledError:
            raise

    def _get_proxies(self, ground=None):
        if ground:
            proxies = self.GROUND_PROXY_MAP.get(ground, self.GROUND_PROXY_DEFAULT)
        else:
            proxies = {i for li in self.GROUND_PROXY_MAP.values() for i in li}

        return list(proxies)
