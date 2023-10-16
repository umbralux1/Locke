from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_payment_methods(site: str, time: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Crypto Bot (Только криптовалюта)",
                    callback_data=f"buy_sub|crypto_bot|{site}|{time}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💳 QIWI, Банковская карта, Крипта",
                    callback_data=f"buy_sub|any_pay|{site}|{time}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 QIWI, Банковская карта #2",
                    callback_data=f"buy_sub|payok|{site}|{time}",
                ),
            ],
        ]
    )
