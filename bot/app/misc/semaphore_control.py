SITE_SEMAPHORE_MAPPING = {
    "ebay.de": 10,
    "anibis.ch": 40,
    "willhaben.at": 1,
    "olx": 40,
    "carousell": 15,
    "etsy": 1,
    "depop": 30,
}

FAST_SPEED = 60


def handler_grouper_by_site(site):
    if site in ["olx.kz", "olx.uz", "olx.ua", "olx.pl", "olx.ro", "olx.pt", "olx.bg"]:
        return "olx"
    elif site in [
        "carousell.sg",
        "carousell.ph",
        "carousell.ca",
        "carousell.nz",
        "carousell.tw",
        "carousell.my",
        "carousell.hk",
        "carousell.id",
        "carousell.au",
    ]:
        return "carousell"
    elif site in [
        "wallapop.es",
        "wallapop.pt",
        "wallapop.uk",
        "wallapop.fr",
        "wallapop.it",
    ]:
        return "wallapop"
    elif site in [
        "depop.au",
        "depop.fr",
        "depop.it",
        "depop.de",
        "depop.uk",
        "depop.us",
    ]:
        return "depop"
    elif site in [
        "etsy.pl",
        "etsy.sg",
        "etsy.il",
        "etsy.at",
        "etsy.hk",
        "etsy.nz",
        "etsy.se",
        "etsy.ch",
        "etsy.de",
        "etsy.au",
        "etsy.it",
        "etsy.fr",
        "etsy.es",
        "etsy.br",
        "etsy.mx",
        "etsy.ca",
        "etsy.us",
        "etsy.hu",
        "etsy.be",
        "etsy.my",
        "etsy.nl",
        "etsy.uk",
        "etsy.no",
    ]:
        return "etsy"
    else:
        return site


async def get_semaphore_amount_by_site(site, items):
    semaphore_amount = SITE_SEMAPHORE_MAPPING.get(
        handler_grouper_by_site(site), "FAST_SPEED"
    )

    if semaphore_amount == "FAST_SPEED":
        semaphore_amount = FAST_SPEED

    return min(len(items), semaphore_amount)
