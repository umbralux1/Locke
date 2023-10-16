import os
import ssl

from loguru import logger

ADMINS = (384305307, 490168360)
CHATS = {
    "support": -4046299097,
    "referrals": -4057754214,
    "news": -1001848812358,
    "logs": -4054320265,
    "pay_logs": -4053949317,
    "activity": -4012322054,
}
TIMEZONE_CONFIG = {
    "UTC+0.0": "Africa/Abidjan",
    "UTC+3.0": "Africa/Addis_Ababa",
    "UTC+1.0": "Africa/Algiers",
    "UTC+2.0": "Africa/Blantyre",
    "UTC-9.0": "America/Adak",
    "UTC-8.0": "America/Anchorage",
    "UTC-4.0": "America/Anguilla",
    "UTC-3.0": "America/Araguaina",
    "UTC-5.0": "America/Atikokan",
    "UTC-6.0": "America/Belize",
    "UTC-7.0": "America/Creston",
    "UTC-2.0": "America/Godthab",
    "UTC-2.5": "America/St_Johns",
    "UTC+11.0": "Antarctica/Casey",
    "UTC+7.0": "Antarctica/Davis",
    "UTC+10.0": "Antarctica/DumontDUrville",
    "UTC+5.0": "Antarctica/Mawson",
    "UTC+12.0": "Antarctica/McMurdo",
    "UTC+6.0": "Antarctica/Vostok",
    "UTC+4.0": "Asia/Baku",
    "UTC+8.0": "Asia/Brunei",
    "UTC+5.5": "Asia/Calcutta",
    "UTC+9.0": "Asia/Chita",
    "UTC+4.5": "Asia/Kabul",
    "UTC+5.8": "Asia/Kathmandu",
    "UTC+6.5": "Asia/Rangoon",
    "UTC+3.5": "Asia/Tehran",
    "UTC-1.0": "Atlantic/Cape_Verde",
    "UTC+9.5": "Australia/Adelaide",
    "UTC+8.8": "Australia/Eucla",
    "UTC+10.5": "Australia/LHI",
    "UTC-10.0": "Etc/GMT+10",
    "UTC-11.0": "Etc/GMT+11",
    "UTC-12.0": "Etc/GMT+12",
    "UTC+13.0": "Etc/GMT-13",
    "UTC+14.0": "Etc/GMT-14",
    "UTC+12.8": "NZ-CHAT",
    "UTC-9.5": "Pacific/Marquesas",
}
ITEMS_POOL = {}
SENDER_STATUS_DB = {}
URLS_POOL = {}
URL_HISTORY = []
TOKEN_ERRORS = {}
USER_MUTEX = {}
MANUALS = {
    "ebay.de": "1",
    "olx": "1",
    "anibis.ch": "https://google.com/",
}


# CONFIG
BOT_TOKEN = os.environ.get("BOT_TOKEN")
##REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = os.environ.get("REDIS_PORT", 1111)
PGUSER = os.environ["POSTGRES_USER"]
PGPASSWORD = os.environ["POSTGRES_PASSWORD"]
PGDATABASE = os.environ["POSTGRES_DB"]
REDIS_PASS = os.environ["REDIS_PASSWORD"]
PROD = bool(int(os.environ.get("PROD", 0)))
###PGHOST = "postgres"
PGHOST = "localhost"
LOG_DIR = os.environ.get("LOG_DIR")

# LIMITS
LIMIT_ADS_MAX = 100
LIMIT_ADS_MIN = 10
LIMIT_MAX_LINKS = 10
LIMIT_MAX_PRESETS = 20
LIMIT_MAX_PRESET_NAME_LENGTH = 11
CUSTOM_TEXT_LIMIT = 10
CUSTOM_TEXT_NAME_LENGTH_LIMIT = 10
CUSTOM_TEXT_LIMIT_LENGTH = 3900
CUSTOM_TEXT_OFFSET_LIMIT = 1100
WHATSAPP_CHECK_LIMIT_PER_DAY = 17_000
MAX_TOKEN = 10

# API
CRYPTO_BOT_API = "1"
CURRENT_BOT_LINK = "@1"
ANYPAY_API = "1"
ANYPAY_LC_API = "1"
ANYPAY_SHOP_ID = "1"
PAYOK_SHOP_ID = "1"
PAYOK_API = "1"
PAYOK_LC_API = "1"
PAYOK_LC_API_ID = 640
WA_CHECK_USER = "1"
WA_CHECK_API = "1"


# TIMINGS
URLS_POOL_CYCLE_SEC = 3
URLS_POOL_WATCH_CYCLE_SEC = 60
ITEMS_POOL_CYCLE_SEC = 0.5
MAX_PARSER_TIME_IN_MIN = 32
MAX_PARSER_TIME_IN_MIN_WATCH = 122

# LOCALES
PHONE_SEARCH_ONLY = 0
PHONE_SEARCH_AND_WITHOUT = 1
PHONE_SEARCH_WITHOUT_ONLY = 2
PHONE_SEARCH_SELF = 3
BL_UNSEEN_ONLY = 1
BL_SHARED = 2


# RESOURCES
logger.debug(PROD)

if PROD:
    BANNER_VIDEO = "https://phonoteka.top/uploads/posts/2021-04/1619214155_56-phonoteka_org-p-chernii-prozrachnii-fon-58.jpg"  # это заглушка
    REFERRAL_VIDEO = "https://phonoteka.top/uploads/posts/2021-04/1619214155_56-phonoteka_org-p-chernii-prozrachnii-fon-58.jpg"  # это заглушка
else:
    BANNER_VIDEO = "https://phonoteka.top/uploads/posts/2021-04/1619214155_56-phonoteka_org-p-chernii-prozrachnii-fon-58.jpg"  # это заглушка
    REFERRAL_VIDEO = "https://phonoteka.top/uploads/posts/2021-04/1619214155_56-phonoteka_org-p-chernii-prozrachnii-fon-58.jpg"  # это заглушка

PHOTO_NOT_FOUND_IMG_LINK = (
    "https://cskashop.ru/upload/iblock/ac3/fsllm9cv8l5cbsgm2b1hunkhgsexzbsg"
    "/4a1a05b5_79ef_11ec_8b88_5439dfca572b_4049ac98_79f5_11ec_8b88_5439dfca572b.jpeg"
)

ssl_context = ssl.create_default_context()
ssl_context.set_ciphers("AES128-SHA")
