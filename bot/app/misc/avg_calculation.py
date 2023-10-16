import traceback
from collections import defaultdict
from datetime import datetime
from time import perf_counter
from urllib.parse import urlparse

import ciso8601
from loguru import logger

from app import db


def try_convert_value(val, mode):
    try:
        if mode == "digit":
            return float(val.split()[0]) if isinstance(val, str) else val
        elif mode == "dates":
            return (
                ciso8601.parse_datetime(val).timestamp()
                if isinstance(val, str)
                else val
            )
    except Exception as e:
        ...


def calculate_avg(records, mode="digit"):
    values = []

    for record in records:
        val = next(iter(record.values()), None)
        if val is None or "N/A" in str(val):
            continue

        converted_val = try_convert_value(val, mode)
        if converted_val is not None:
            values.append(converted_val)

    if not values:
        return "N/A"

    avg_value = sum(values) / len(values)
    return (
        int(avg_value)
        if mode == "digit"
        else datetime.fromtimestamp(avg_value).strftime("%d-%m-%Y")
    )


def generate_avg_text(daily, monthly, title, mode="digit"):
    avg_values = {
        "за день": calculate_avg(daily, mode),
        "за месяц": calculate_avg(monthly, mode),
    }
    lines = [
        f"<i>• {period}: <code>{avg}</code></i>"
        for period, avg in avg_values.items()
        if avg != "N/A"
    ]
    return f"\n<b>{title}</b>\n" + "\n".join(lines) if lines else ""


def calculate_seller_delivery_ratio(daily, monthly, all_time):
    def calculate_ratio(records):
        total_records = len(records)
        if total_records == 0:
            return "N/A"

        good_records = sum(record["delivery"] != "N/A" for record in records)
        return round((good_records / total_records) * 100, 2)

    ratio_values = {
        "за день": calculate_ratio(daily),
        "за месяц": calculate_ratio(monthly),
        # "за все время": calculate_ratio(all_time),
    }

    return generate_text(ratio_values, "Процентное соотношение товара с доставкой")


def generate_text(avg_values: dict, title: str) -> str:
    add_text = "1-" if "цена" in title else ""
    add_text2 = "%" if "Процентное" in title else ""
    add_text_lines = [
        f"<i>• {period}: <code>{add_text}{avg}{add_text2}</code></i>"
        for period, avg in avg_values.items()
        if str(avg) != "N/A"
    ]

    return f"\n<b>{title}</b>\n" + "\n".join(add_text_lines) if add_text_lines else ""


def process_unique_records(records, mode="digit"):
    unique_records = defaultdict(int)
    for record in records:
        if "|" in record["error_details"]:
            url, *_, value = record["error_details"].split("|")

            if mode == "digit":
                value = int(value)
            else:
                value = int(ciso8601.parse_datetime(value).timestamp())

            parsed_url = urlparse(url)
            clean_url = (
                f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}".casefold()
            )

            unique_records[clean_url] = max(unique_records.get(clean_url, 0), value)

    return list(unique_records.values())


def preprocess_records(records, mode="digit"):
    if not records:
        return []

    processed = []
    for record in records:
        if "|" in record["error_details"]:
            url, *_, value = record["error_details"].split("|")
            if mode == "digit":
                value = int(value)
            else:
                value = int(ciso8601.parse_datetime(value).timestamp())

            parsed_url = urlparse(url)
            clean_url = (
                f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}".casefold()
            )

            processed.append((clean_url, value))

    return processed


def process_unique_records_optimized(preprocessed_records):
    unique_records = defaultdict(int)
    for clean_url, value in preprocessed_records:
        unique_records[clean_url] = max(unique_records.get(clean_url, 0), value)

    return list(unique_records.values())


def process_data(data, column):
    today = datetime.now().date()
    this_month_first_day = today.replace(day=1)
    return (
        [record for record in data if record["record_date"].date() == today],
        [
            record
            for record in data
            if record["record_date"].date() >= this_month_first_day
        ],
        data,
    )


async def get_avg_values_by_period(site, column, with_person_id=False):
    db_func = (
        db.get_avg_for_column_with_person_id
        if with_person_id
        else db.get_avg_for_column
    )
    all_time_data = await db_func(site=site, column=column, days=31)
    return process_data(all_time_data, column)


def calculate_seller_rating_ratio(daily, monthly, all_time, additional_avg=None):
    def calculate_ratio(records):
        unique_sellers = {}
        for record in records:
            person_id = record["person_id"]
            rating = record["rating"]

            if person_id not in unique_sellers or (
                unique_sellers[person_id] == 0 and rating == 1
            ):
                unique_sellers[person_id] = rating

        total_sellers = len(unique_sellers)
        if total_sellers == 0:
            return "N/A"

        good_sellers = sum(rating == 1 for rating in unique_sellers.values())
        return round((good_sellers / total_sellers) * 100, 2)

    ratio_values = {
        "за день": calculate_ratio(daily),
        "за месяц": calculate_ratio(monthly),
        # "за все время": calculate_ratio(all_time),
    }

    return generate_text(ratio_values, "Процентное соотношение продавцов с рейтингом")
