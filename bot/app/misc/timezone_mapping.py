from datetime import datetime

import pytz

from app import db


def get_time_in_timezone(site):
    timezone_mapping = {
        "pl": "Europe/Warsaw",
        "ro": "Europe/Bucharest",
        "kz": "Europe/Bucharest",
    }

    return datetime.now(
        pytz.timezone(timezone_mapping.get(site.split(".")[-1]))
    ).strftime("%H:%M")


async def convert_to_user_timezone(dt: datetime, user_id) -> datetime:
    user_timezone = await db.get_timezone(user_id=user_id) or "Europe/Moscow"

    user_tz = pytz.timezone(user_timezone)
    return dt.astimezone(user_tz)
