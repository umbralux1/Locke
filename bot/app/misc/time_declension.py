from datetime import datetime

import ciso8601
import pytz
from dateutil.relativedelta import relativedelta

moscow = pytz.timezone("Europe/Moscow")


def pluralize(number, forms):
    if number % 10 == 1 and number % 100 != 11:
        form = 0
    elif 2 <= number % 10 <= 4 and (number % 100 < 10 or number % 100 >= 20):
        form = 1
    else:
        form = 2
    return forms[form]


def humanize_date(date_string, add_word=True):
    if isinstance(date_string, str):
        # date_format = "%Y-%m-%d %H:%M:%S.%f"
        # date_obj = datetime.strptime(date_string, date_format)
        if date_string == "N/A":
            return date_string

        date_obj = ciso8601.parse_datetime(date_string)

    elif isinstance(date_string, datetime):
        date_obj = date_string
    else:
        return date_string

    keyword = "назад" if add_word else ""

    now = datetime.now(tz=date_obj.tzinfo) if date_obj.tzinfo else datetime.now()

    difference = relativedelta(now, date_obj)

    years = abs(difference.years)
    months = abs(difference.months)
    days = abs(difference.days)
    hours = abs(difference.hours)
    minutes = abs(difference.minutes)
    seconds = abs(difference.seconds)

    result = ""

    if days == 0 and years == 0 and months == 0:
        if hours > 0:
            result += f"{hours} {pluralize(hours, ['час ', 'часа ', 'часов '])}"
        if minutes > 0:
            result += (
                f"{minutes} {pluralize(minutes, ['минута ', 'минуты ', 'минут '])}"
            )
        else:
            result += (
                f"{seconds} {pluralize(seconds, ['секунда ', 'секунды ', 'секунд '])}"
            )
    else:
        if years > 0:
            result += f"{years} {pluralize(years, ['год ', 'года ', 'лет '])}"
        if months > 0:
            result += f"{months} {pluralize(months, ['месяц ', 'месяца ', 'месяцев '])}"
        if days > 0:
            result += f"{days} {pluralize(days, ['день ', 'дня ', 'дней '])}"
        if hours > 0:
            result += f"{hours} {pluralize(hours, ['час ', 'часа ', 'часов '])}"

    return f"{result}{keyword}"


def humanize_date_v2(new_end_date):
    months_rus = [
        "",
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]

    return f"{new_end_date.day} {months_rus[new_end_date.month]} {new_end_date.year} {new_end_date.strftime('%H:%M')}"
