from app.sites_config import sites


def get_cash_by_day(days, site):
    site_info = sites.get(site, {})
    price_by_day_amount = site_info.get("price_by_day_amount", {})
    percent_cash = price_by_day_amount.get(int(days), 250)
    percent_cash += percent_cash / 100 * 7.5

    return f"💰 ~{percent_cash}р."
