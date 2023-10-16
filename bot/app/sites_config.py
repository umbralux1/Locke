from app.states.states import (
    Anibis,
    Willhaben,
)

simple_price = {
    1: 1,
    3: 1,
    7: 1,
    30: 1,
}

lower_cost = {
    1: 1,
    3: 1,
    7: 1,
    30: 1,
}

sites = {
    "anibis.ch": {
        "feature": "",
        "filters": (
            "Кол-во объявлений продавца",
            "Дата регистрации продавца",
            "Дата создания объявления",
        ),
        "is_changeable": True,
        "price_by_day_amount": simple_price,
        "need_tokens": False,
        "can_give_for_free": True,
        "init_state": Anibis.price,
        "link_example": "https://www.anibis.ch/fr/c/toutes-les-rubriques?fts=apple",
        "link_signature": "anibis.ch/",
    },
    "willhaben.at": {
        "feature": "Нет номеров телефона",
        "filters": (
            "Кол-во объявлений продавца",
            "Дата регистрации продавца",
            "Дата создания объявления",
        ),
        "is_changeable": False,
        "price_by_day_amount": lower_cost,
        "need_tokens": False,
        "can_give_for_free": True,
        "init_state": Willhaben.price,
        "link_example": "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?isNavigation=true&keyword=apple",
        "link_signature": "willhaben.at/",
    },
}
sorted_sites = sorted(list(sites.keys()), key=lambda x: x.lower())
