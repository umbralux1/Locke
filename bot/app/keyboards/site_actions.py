import ujson
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import db
from app.keyboards.all_sites_menu import ShowSite


def get_site_actions_btns(site, is_feature):
    if any(record.get("site") == site for record in is_feature):
        feature_text = "⭐ Удалить из избранных"
        feature_key = "delete_from_features"
    else:
        feature_text = "⭐ В избранное"
        feature_key = "add_to_features"

    markup_data = [
        [
            InlineKeyboardButton(
                text="🔍 Стандартный",
                callback_data=f"start_parser|standard|{site}",
            ),
            InlineKeyboardButton(
                text="💤 Фоновый",
                callback_data=f"start_parser|backgrnd|{site}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💾 Пресеты",
                callback_data=f"presets|{site}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💬 Кастомный текст",
                callback_data=f"custom_text|{site}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔄 Сменить площадку",
                callback_data=f"change_sub|{site}",
            ),
        ],
        [
            InlineKeyboardButton(
                text=feature_text,
                callback_data=f"{feature_key}|{site}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💰 Продлить подписку",
                callback_data=f"renew_subscription|{site}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="◀",
                callback_data="back_to_main_menu",
            ),
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=markup_data)


async def get_saved_user_links(site, user_id):
    saved_links_menu = InlineKeyboardBuilder()
    links = await db.get_saved_user_links(user_id, site)

    for row_id, link in links:
        saved_links_menu.button(
            text=link.replace("\n", " "), callback_data=f"links_run|{row_id}"
        )

    saved_links_menu.button(
        text="◀",
        callback_data=ShowSite(
            site=site,
            show_key="show_site",
        ).pack(),
    )

    saved_links_menu.adjust(1)
    return saved_links_menu.as_markup()


def get_result_btns(stat_id, json_output=False, remove_renew_keyboard=False):
    inline_keyboard = [
        [
            {"text": "📄 .TXT", "callback_data": f"format_result|{stat_id}|txt"},
            {"text": "🌐 .HTML", "callback_data": f"format_result|{stat_id}|html"},
        ],
        [
            {"text": "📇 .VCF", "callback_data": f"format_result|{stat_id}|vcf"},
            {"text": "📊 .CSV", "callback_data": f"format_result|{stat_id}|csv"},
        ],
        [
            {"text": "💬 Сообщения", "callback_data": f"format_result|{stat_id}|msg"},
            {
                "text": "📰 Telegraph",
                "callback_data": f"format_result|{stat_id}|telegraph",
            },
        ],
        [
            {
                "text": "📄 Список (.TXT)",
                "callback_data": f"format_result|{stat_id}|list_txt",
            },
            {
                "text": "📊 .XLSX",
                "callback_data": f"format_result|{stat_id}|xlsx",
            },
        ],
        [
            {
                "text": "🔽 Экспортировать для Sender",
                "callback_data": f"format_result|{stat_id}|sender",
            }
        ],
        [
            {
                "text": "🤖 Авто рассылка",
                "callback_data": f"auto_sender|{stat_id}",
            }
        ],
        [
            {
                "text": "Получить отклоненные объявления",
                "callback_data": f"get_error_result|{stat_id}",
            }
        ],
    ]

    if not remove_renew_keyboard:
        inline_keyboard.append(
            [
                {
                    "text": "Обновить статистику",
                    "callback_data": f"renew_stats|{stat_id}",
                }
            ]
        )

    if json_output:
        return ujson.dumps({"inline_keyboard": inline_keyboard}, ensure_ascii=False)

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


stop_parser = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="❌ Завершить парсинг",
                callback_data="stop_active_parser",
            )
        ],
    ]
)

stop_parser_json = {
    "inline_keyboard": [
        [{"text": "❌ Завершить парсинг", "callback_data": "stop_active_parser"}]
    ]
}

stop_sender_button = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="❌ Завершить рассылку", callback_data="stop_sender")]
    ]
)
