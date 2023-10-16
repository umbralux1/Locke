import asyncio

from aiogram import types, Router
from aiogram.filters import Command

from app import dp
from app.filters.admin import IsAdmin
from app.misc.scheduler import proxy_check, clear_redis_old_data

router = Router()
dp.include_router(router)


@router.message(Command("check_proxy"), IsAdmin())
async def check_proxy(msg: types.Message):
    await msg.answer("Ожидайте....")

    asyncio.create_task(proxy_check())


@router.message(Command("clear_redis"), IsAdmin())
async def clear_redis(msg: types.Message):
    await msg.answer("Ожидайте....")

    asyncio.create_task(clear_redis_old_data())
