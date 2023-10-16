import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery

from app import dp
from app.filters.admin import IsAdmin
from app.sites_config import sites

router = Router()
dp.include_router(router)


async def run_site_checker():
    for site in list(sites):
        if site == 'ebay.de':
            get_url_test = 5


@router.callback_query(F.data == "check_sites", IsAdmin())
async def check_sites(query: CallbackQuery):
    await query.message.answer("Ожидайте....")

    asyncio.create_task(run_site_checker())
