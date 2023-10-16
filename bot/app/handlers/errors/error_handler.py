from aiogram import F
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramForbiddenError,
)
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent, Message
from loguru import logger

from app import dp


@dp.error(ExceptionTypeFilter(TelegramNetworkError), F.update.message.as_("message"))
async def network_error(event: ErrorEvent, message: Message):
    logger.debug(f"TelegramBadRequest error {event}")


@dp.error(ExceptionTypeFilter(TelegramForbiddenError), F.update.message.as_("message"))
async def forbidden_error(event: ErrorEvent, message: Message):
    logger.debug(f"TelegramForbiddenError error {event}")


@dp.error(ExceptionTypeFilter(TelegramBadRequest), F.update.message.as_("message"))
async def bad_request_error(event: ErrorEvent, message: Message):
    logger.debug(f"TelegramBadRequest error {event}")
