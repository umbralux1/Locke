from aiogram.filters.state import StatesGroup, State


class Olx(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    item_views = State()
    rating_delete = State()
    has_delivery = State()


class OlxNoTokens(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    item_views = State()
    rating_delete = State()
    success_delivery = State()
    has_delivery = State()


class OlxTokens(StatesGroup):
    price = State()
    tokens = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    item_views = State()
    rating_delete = State()
    success_delivery = State()
    has_delivery = State()


class EbayDe(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    item_views = State()
    rating_delete = State()
    has_delivery = State()


class Anibis(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()


class Willhaben(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()


class Carousell(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    rating_delete = State()
    has_delivery = State()


class Wallapop(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_item_sold_amount = State()
    seller_item_bought_amount = State()
    seller_join_date = State()
    item_views = State()
    item_insert_date = State()
    rating_delete = State()
    success_delivery = State()
    has_delivery = State()


class Depop(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_item_sold_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    rating_delete = State()


class Subito(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    rating_delete = State()


class Etsy(StatesGroup):
    price = State()
    seller_item_amount = State()
    seller_item_sold_amount = State()
    seller_join_date = State()
    item_insert_date = State()
    rating_delete = State()
    gender = State()
