from aiogram import Bot
from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from redis.asyncio.client import Redis
from redis.asyncio.connection import ConnectionPool

from . import config as cfg
from .config import REDIS_PASS
from .db import Database
from .middlewares.loggin import LoggerMiddleware
from .middlewares.throttle import ThrottlingMiddleware

bot = Bot(
    token=cfg.BOT_TOKEN,
    parse_mode="HTML",
    disable_web_page_preview=True,
)

storage = RedisStorage.from_url(
    # f"redis://{cfg.REDIS_HOST}:{cfg.REDIS_PORT}",
    f"redis://{cfg.REDIS_HOST}:{cfg.REDIS_PORT}",
)


pool = ConnectionPool(
    host=cfg.REDIS_HOST,port=cfg.REDIS_PORT, db=0
)
# redis = Redis(connection_pool=pool, max_connections=1000)
redis = Redis(connection_pool=pool)


dp = Dispatcher(
    storage=storage,
)

db = Database()

job_stores = {
    "default": RedisJobStore(
        host=cfg.REDIS_HOST,port=cfg.REDIS_PORT, db=1
    )
}
scheduler_ = AsyncIOScheduler(timezone="Europe/Moscow", jobstores=job_stores)

dp.message.middleware(ThrottlingMiddleware())
dp.callback_query.middleware(ThrottlingMiddleware())

dp.message.middleware(LoggerMiddleware())
dp.callback_query.middleware(LoggerMiddleware())

logger.info("Middlewares are successfully configured")
