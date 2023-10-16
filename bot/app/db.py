import asyncio
import re
import traceback
import uuid
from datetime import datetime, timedelta
from time import perf_counter
from typing import Union
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import aiohttp
import asyncpg
import ujson
from aiohttp import TCPConnector, ClientTimeout
from asyncpg import Pool
from loguru import logger

from app import config
from app.misc.notify import send_text


async def detect_sql_injection(input_str, user_id):
    # logger.debug(input_str)
    if input_str is None:
        input_str = ""

    input_str = str(input_str)
    # Черный список паттернов

    try:
        input_str = unquote(input_str)
    except Exception:
        logger.debug(traceback.format_exc())

    patterns = [
        r"\bbenchmark\(\d+,",
        r"\\x00",
        r"\bsleep\s*\(.*\)\s*",
        r"\b\d+::int\b",
        r"\b\d+::integer\b",
        r"\bpg_client_encoding\(\)",
        r"\bget_current_ts_config\(\)",
        r"\bquote_literal\(",
        r"\bsleep\s*\(\d+\)\b",
        r"\bcurrent_database\(\)",
        r"\bCREATE TABLE\b",
        # r"\bCOPY\b",
        r"‘/etc/passwd’",
        r"\b(select|union|drop|update)\b[\s(]+(?![A-Z-])",
        r"\bpg_sleep\(",
        r"union\s+(all\s+)?select",
        r"\bwaitfor\s+delay",
        r"\brandomblob\(",
        r"\band\s+\d+=\d+",
        r"\bor\s+\d+=\d+",
        r";--",
        r"\bversion\(\)",
        # r"\buser\b(?![^<]*>)",
        r"\bcurrent_user\b",
        r"\bsession_user\b",
        r"usename\s+from\s+pg_user",
        r"\bgetpgusername\(\)",
        r"\bpg_user\b",
        r"\bpg_shadow\b",
        r"\bcurrent_database\(\)",
        r"\bpg_database\b",
        r"\bpg_class\b",
        r"\bpg_namespace\b",
        r"\bpg_attribute\b",
        r"\bpg_type\b",
        r"pg_catalog\.pg_class",
        r"\bpg_catalog\b",
        r"\bDISTINCT\b",
        # r"\bOFFSET\b",
        r"ORDER\s+BY",
        # r"CAST\s*\(",
        # r"CASE\b",
        # r"CHR\s*\(",
        r"\bpg_sleep\s*\(",
        r"REPLACE\s+FUNCTION",
        # r"\bsystem\s*\(",
        r"\bcurrent_setting\s*\(",
        r"\binet_server_addr\(\)",
        r"\binet_server_port\(\)",
        r"\bINSERT\s+INTO\b",
    ]

    enhanced_patterns = [
        r"\bAND\s*\d+=\d+\b",
        r"OR\s*\d+=\d+\b",
        r"\bDROP\s+TABLE\b",
        r"\bSELECT\s+\*\s+FROM\b",
        r"\bexec\b",
        r"\bmaster\.\.",
        # r"\b#\b",
        r"/\*",
        r"\*/",
        r"(\d|')\s*;\s*(DROP|SELECT|INSERT)\b",
        r"(\b|')\s*;\s*DROP\b",
        r"(\b|')\s*;\s*SELECT\b",
        r"\bUNION\b.*\bSELECT\b",
        r"\bUNION\s+ALL\b",
        r"\bUNION\s+DISTINCT\b",
    ]

    patterns += enhanced_patterns

    try:
        parsed = urlparse(input_str)
        if parsed.scheme and parsed.netloc:
            # Если это URL, то берём только query-часть для проверки
            input_str = "&".join(
                [f"{k}={v[0]}" for k, v in parse_qs(parsed.query).items()]
            )
    except Exception:
        logger.debug(traceback.format_exc())

    async with aiohttp.ClientSession(
        json_serialize=ujson.dumps,
        timeout=ClientTimeout(total=20),
        connector=TCPConnector(limit_per_host=10_000, limit=10_000),
    ) as sess:
        for pattern in patterns:
            if re.search(pattern, input_str, re.IGNORECASE):
                raise ValueError(input_str)


class Database:
    def __init__(self):
        self.pool: Union[Pool, None] = None

    async def create(self, max_size=50, min_size=10):
        pool = await asyncpg.create_pool(
            user=config.PGUSER,
            password=config.PGPASSWORD,
            host=config.PGHOST,
            port=3333,
            database=config.PGDATABASE,
            max_size=max_size,
            min_size=min_size,
            max_inactive_connection_lifetime=3,
        )
        self.pool = pool

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def create_table_custom_msg_text(self):
        sql = """
        CREATE TABLE IF NOT EXISTS user_custom_text(
        id bigserial NOT NULL,
        user_id BIGINT NOT NULL,
        text_body TEXT NOT NULL,
        text_title TEXT NOT NULL,
        site TEXT NOT NULL,
        UNIQUE(user_id, text_title, site)
        )
        """
        sql_index = """CREATE INDEX IF NOT EXISTS index_user_id_site ON user_custom_text(user_id, site);"""

        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_worker_views(self):
        sql = """
        CREATE TABLE IF NOT EXISTS worker_views (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL,
            site TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            item_id TEXT NOT NULL
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_worker_views_item_site ON worker_views(item_id, site)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_user_word_complete(self):
        sql = """
        CREATE TABLE IF NOT EXISTS user_word_complete (
            id bigserial PRIMARY KEY,
            user_id BIGINT NOT NULL,
            keyword TEXT NOT NULL,
            site TEXT NOT NULL,
            save_type TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, site, save_type)
        );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_tickets(self):
        sql = """
        CREATE TABLE IF NOT EXISTS tickets (
            id bigserial NOT NULL,
            owner_chat_id BIGINT NOT NULL,
            owner_username TEXT NOT NULL,
            support_chat_id BIGINT NOT NULL,
            support_username TEXT NOT NULL,
            ticket_status TEXT NOT NULL,
            ticket_detail TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_run_stats(self):
        sql = """
        CREATE TABLE IF NOT EXISTS run_stats (
            id bigserial NOT NULL,
            site TEXT NOT NULL,
            keyword TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_run_stats_site_date ON run_stats (site, date)"
        sql_index2 = "CREATE INDEX IF NOT EXISTS idx_run_stats_site_keyword_date ON run_stats (site, keyword, date)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_user_parser_status(self):
        sql = """
        CREATE TABLE IF NOT EXISTS user_parser_status (
            user_id BIGINT UNIQUE,
            status TEXT NOT NULL
            );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_proxy_manager_blacklist(self):
        sql = """
        CREATE TABLE IF NOT EXISTS proxy_manager_blacklist (
            proxy TEXT UNIQUE NOT NULL
            );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_running_parser_recovery_info(self):
        sql = """
        CREATE TABLE IF NOT EXISTS running_parser_recovery_info (
            chat_id BIGINT NOT NULL,
            info TEXT NOT NULL
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_chat_id_running_parser ON running_parser_recovery_info (chat_id);"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_throttling_control_proxy(self):
        sql = """
        CREATE TABLE IF NOT EXISTS throttling_control_proxy (
            id bigserial NOT NULL,
            proxy TEXT NOT NULL,
            site TEXT NOT NULL,
            status TEXT,
            throttled_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_proxy_site ON throttling_control_proxy (proxy, site);"
        sql_index2 = "CREATE INDEX IF NOT EXISTS idx_site_status ON throttling_control_proxy (site, status);"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_stats_ticker(self):
        sql = """
        CREATE TABLE IF NOT EXISTS stats_ticker (
            id bigserial NOT NULL,
            stat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            site TEXT NOT NULL,
            last_msg TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_stats_ticker_user_stat ON stats_ticker (user_id, stat_id)"
        sql_index2 = (
            "CREATE INDEX IF NOT EXISTS idx_stats_ticker_date ON stats_ticker (date)"
        )
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_parser_history(self):
        sql = """
        CREATE TABLE IF NOT EXISTS parser_history (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL,
            person_id TEXT NOT NULL,
            stat_id BIGINT NOT NULL,
            title TEXT NOT NULL,
            price TEXT NOT NULL,
            location TEXT,
            description TEXT,
            delivery TEXT,
            possible_phones TEXT,
            photo TEXT,
            person_registration_date TEXT,
            email TEXT,
            person_link TEXT,
            gender TEXT,
            phone TEXT,
            ads_number_buyed INT,
            ads_number_selled INT,
            our_views INT,
            success_delivery_count INT,
            ads_number INT,
            creation_date TEXT,
            views INT,
            ad_link TEXT NOT NULL,
            person_name TEXT,
            rating INT,
            site TEXT NOT NULL,
            record_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_user_stat ON parser_history (user_id, stat_id)"
        sql_index2 = "CREATE INDEX IF NOT EXISTS idx_site_date ON parser_history (site, record_date)"
        # sql_index3 = "CREATE INDEX IF NOT EXISTS idx_compound_ads_number ON parser_history (site, ad_link, ads_number DESC, record_date DESC)"
        # sql_index4 = "CREATE INDEX IF NOT EXISTS idx_compound_price ON parser_history (site, ad_link, price DESC, record_date DESC)"
        # sql_index5 = "CREATE INDEX IF NOT EXISTS idx_compound_person_registration_date ON parser_history (site, ad_link, person_registration_date DESC, record_date DESC)"
        # sql_index6 = "CREATE INDEX IF NOT EXISTS idx_compound_creation_date ON parser_history (site, ad_link, creation_date DESC, record_date DESC)"
        # sql_index7 = "CREATE INDEX IF NOT EXISTS idx_compound_delivery ON parser_history (site, ad_link, delivery DESC, record_date DESC)"
        # sql_index8 = "CREATE INDEX IF NOT EXISTS idx_compound_views ON parser_history (site, ad_link, views DESC, record_date DESC)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)
            # await con.execute(sql_index3)
            # await con.execute(sql_index4)
            # await con.execute(sql_index5)
            # await con.execute(sql_index6)
            # await con.execute(sql_index7)
            # await con.execute(sql_index8)

    async def create_table_parser_stats_history(self):
        sql = """
        CREATE TABLE IF NOT EXISTS parser_stats_history (
            id bigserial NOT NULL PRIMARY KEY,
            stat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            site TEXT NOT NULL,
            error_code TEXT NOT NULL,
            error_details TEXT,
            record_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_parser_stats_user_stat ON parser_stats_history (user_id, stat_id)"
        sql_index2 = "CREATE INDEX IF NOT EXISTS idx_parser_stats_site_error_date ON parser_stats_history (site, error_code, record_date)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_user_saved_links(self):
        sql = """
        CREATE TABLE IF NOT EXISTS user_saved_links (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL,
            site TEXT NOT NULL,
            link TEXT NOT NULL DEFAULT '0',
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_user_saved_links_user_site ON user_saved_links (user_id, site)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_payments_stats(self):
        sql = """
        CREATE TABLE IF NOT EXISTS payments_stats (
            id bigserial NOT NULL,
            admin_id BIGINT NOT NULL,
            username TEXT NOT NULL,
            place TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            days_amount INT NOT NULL
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_payments_stats_date ON payments_stats (date)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_subscription_change_history(self):
        sql = """
            CREATE TABLE IF NOT EXISTS subscription_change_history (
                id bigserial NOT NULL,
                user_id BIGINT NOT NULL,             -- идентификатор пользователя
                old_platform TEXT,                    -- старая площадка
                new_platform TEXT NOT NULL,           -- новая площадка
                old_subscription_period TIMESTAMP,      -- старый период подписки 
                new_subscription_period TIMESTAMP NOT NULL, -- новый период подписки 
                change_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP        -- дата и время изменения подписки
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_subscription_change_user_id ON subscription_change_history (user_id)"
        sql_index2 = "CREATE INDEX IF NOT EXISTS idx_subscription_change_date ON subscription_change_history (change_date)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_blacklist_persons(self):
        sql = """
        CREATE TABLE IF NOT EXISTS blacklist_persons (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            site TEXT NOT NULL,
            blacklisted_id TEXT NOT NULL
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_blacklist_persons_site_blacklisted_id ON blacklist_persons (site, blacklisted_id)"
        sql_index2 = "CREATE INDEX IF NOT EXISTS idx_blacklist_persons_user_id_site_blacklisted_id ON blacklist_persons (user_id, site, blacklisted_id)"

        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_wa_credits(self):
        sql = """
        CREATE TABLE IF NOT EXISTS wa_credits (
            id bigserial NOT NULL,
            user_id TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_wa_credits_user_date ON wa_credits (user_id, date)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_user_presets(self):
        sql = """
        CREATE TABLE IF NOT EXISTS user_presets(
        id bigserial NOT NULL,
        share_id TEXT NOT NULL ,
        user_id BIGINT NOT NULL,
        text_body TEXT NOT NULL,
        text_title TEXT NOT NULL,
        site TEXT NOT NULL
        )
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_user_site_title ON user_presets(user_id, site, text_title)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_site_features(self):
        sql = """
        CREATE TABLE IF NOT EXISTS site_features (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL,
            site TEXT NOT NULL
            );
        """
        sql_index = (
            "CREATE INDEX IF NOT EXISTS idx_user_site ON site_features(user_id, site)"
        )
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_blacklisted_words(self):
        sql = """
        CREATE TABLE IF NOT EXISTS blacklisted_words (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL UNIQUE,
            words TEXT NOT NULL DEFAULT ''
            );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_subscriptions_sites(self):
        sql = """
        CREATE TABLE IF NOT EXISTS subscriptions_sites (
            id bigserial NOT NULL,
            user_id BIGINT NOT NULL,
            site TEXT NOT NULL,
            expiry_date TIMESTAMP NOT NULL,
            UNIQUE(user_id, site)
        );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_site_status(self):
        sql = """
        CREATE TABLE IF NOT EXISTS site_status (
            id bigserial NOT NULL,
            site TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL
        );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_payment_info(self):
        sql = """
        CREATE TABLE IF NOT EXISTS payment_info (
            id bigserial NOT NULL,
            payment_id BIGINT NOT NULL,
            username TEXT NOT NULL,
            user_id TEXT NOT NULL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL
            );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_payment_user_payment ON payment_info(user_id, payment_id)"
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)

    async def create_table_user_tokens(self):
        sql = """
        CREATE TABLE IF NOT EXISTS user_tokens (
            id bigserial NOT NULL,
            chat_id BIGINT NOT NULL,
            tokens TEXT NOT NULL,
            site TEXT NOT NULL,
            UNIQUE(chat_id, site)
            );
        """
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def create_table_bot_users(self):
        sql = """
        CREATE TABLE IF NOT EXISTS bot_users (
            id SERIAL,
            user_id BIGINT NOT NULL UNIQUE,
            username TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT '',
            referral_days INT NOT NULL DEFAULT 0,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_tp_banned BOOL DEFAULT FALSE,
            referrer_id BIGINT
        );
        """
        sql_index = "CREATE INDEX IF NOT EXISTS idx_bot_users_referrer_id ON bot_users(referrer_id)"
        sql_index2 = (
            "CREATE INDEX IF NOT EXISTS idx_bot_users_username ON bot_users(username)"
        )
        async with self.pool.acquire() as con:
            await con.execute(sql)
            await con.execute(sql_index)
            await con.execute(sql_index2)

    async def create_table_user_settings(self):
        sql = """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id BIGINT NOT NULL UNIQUE,
                show_photo BOOLEAN DEFAULT TRUE,
                show_title BOOLEAN DEFAULT TRUE,
                show_price BOOLEAN DEFAULT TRUE,
                show_location BOOLEAN DEFAULT TRUE,
                show_desc BOOLEAN DEFAULT TRUE,
                show_views BOOLEAN DEFAULT TRUE,
                old_msg_send BOOLEAN DEFAULT FALSE,
                show_creation_date BOOLEAN DEFAULT TRUE,
                show_delivery BOOLEAN DEFAULT TRUE,
                show_person_name BOOLEAN DEFAULT TRUE,
                show_rating BOOLEAN DEFAULT TRUE,
                show_ads_number BOOLEAN DEFAULT TRUE,
                show_person_joined BOOLEAN DEFAULT TRUE,
                style INT DEFAULT 0,
                compact_view BOOLEAN DEFAULT FALSE,
                only_person_wa BOOLEAN DEFAULT TRUE,
                exclude_cars BOOLEAN DEFAULT TRUE,
                exclude_estate BOOLEAN DEFAULT TRUE,
                exclude_animals BOOLEAN DEFAULT TRUE,
                exclude_services BOOLEAN DEFAULT TRUE,
                exclude_digital_products BOOLEAN DEFAULT TRUE,
                phone_search_type INT DEFAULT 0,
                getter_ads_limit INT DEFAULT 100, 
                blacklist_type INT DEFAULT 0
            );
        """  # добавляй новые параметры выше значения getter_ads_limit тк.к оно захардкодено
        async with self.pool.acquire() as con:
            await con.execute(sql)

    async def init_user_settings(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
            INSERT INTO user_settings (user_id) 
            VALUES ($1)
            ON CONFLICT (user_id) 
            DO NOTHING;
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id)

    async def reset_user_settings(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
            DELETE FROM user_settings WHERE user_id = $1
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id)

        await self.init_user_settings(user_id)

    async def update_user_setting(
        self, user_id: int, setting_name: str, new_value: bool
    ):
        if setting_name not in [
            "show_photo",
            "show_title",
            "show_price",
            "show_location",
            "show_desc",
            "old_msg_send",
            "show_views",
            "show_creation_date",
            "show_delivery",
            "show_person_name",
            "show_rating",
            "show_ads_number",
            "show_person_joined",
            "compact_view",
            "only_person_wa",
            "phone_search_type",
            "blacklist_type",
            "exclude_cars",
            "exclude_estate",
            "exclude_animals",
            "exclude_services",
            "exclude_digital_products",
            "getter_ads_limit",
            "style",
        ]:
            raise AttributeError("Invalid setting name")

        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(setting_name, user_id)
            await detect_sql_injection(new_value, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = f"""
            UPDATE user_settings
            SET {setting_name} = $1
            WHERE user_id = $2
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, new_value, user_id)

    async def get_getter_ads_limit(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
            SELECT getter_ads_limit FROM user_settings WHERE user_id = $1
        """
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def get_configuration_settings(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT * FROM user_settings WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id)

    async def get_user_subscription_site(self, user_id: int, site: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT expiry_date FROM subscriptions_sites WHERE user_id = $1 AND site = $2"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id, site)

    async def get_all_user_subscription_site(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT * FROM subscriptions_sites WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id)

    async def get_all_subscriptions_site(self):
        sql = "SELECT * FROM subscriptions_sites"

        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def add_subscription(self, user_id, site, new_expiry_date):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(new_expiry_date, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        async with self.pool.acquire() as con:
            expiry_date = await self.get_user_subscription_site(user_id, site)

            if expiry_date is None or expiry_date < datetime.now():
                expiry_date = new_expiry_date
            else:
                expiry_date = expiry_date + (new_expiry_date - datetime.now())

            await con.execute(
                """
                INSERT INTO subscriptions_sites(user_id, site, expiry_date) VALUES($1, $2, $3)
                ON CONFLICT (user_id, site)
                DO UPDATE SET expiry_date = $4
                """,
                user_id,
                site,
                expiry_date,
                expiry_date,
            )

            return expiry_date

    async def remove_subscription(self, user_id, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        async with self.pool.acquire() as con:
            await con.execute(
                """
                DELETE FROM subscriptions_sites WHERE user_id = $1 AND site = $2
                """,
                user_id,
                site,
            )

    async def create_ticket(self, owner_chat_id, owner_username, ticket_detail):
        try:
            await detect_sql_injection(owner_username, owner_chat_id)
            await detect_sql_injection(owner_chat_id, owner_chat_id)
            await detect_sql_injection(ticket_detail, owner_chat_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """INSERT INTO tickets(owner_chat_id, owner_username, support_chat_id, support_username, ticket_status, ticket_detail) 
                VALUES($1, $2, $3, $4, $5, $6) RETURNING id"""

        async with self.pool.acquire() as con:
            return await con.fetchval(
                sql, owner_chat_id, owner_username, 0, "", "open", ticket_detail
            )

    async def get_user_blacklisted_words(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT words FROM blacklisted_words WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def add_blacklisted_word(self, user_id, words):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(words, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
                INSERT INTO blacklisted_words (user_id, words)
                VALUES ($1, $2)
                ON CONFLICT (user_id)
                DO UPDATE SET words = $2
                """

        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, words)

    async def add_site_status(self, site, status):
        try:
            await detect_sql_injection(site, status)
            await detect_sql_injection(status, status)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
                INSERT INTO site_status (site, status)
                VALUES ($1, $2)
                ON CONFLICT (site)
                DO UPDATE SET status = $2
                """

        async with self.pool.acquire() as con:
            await con.execute(sql, site, status)

    async def get_site_status(self, site):
        try:
            await detect_sql_injection(site, site)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT status FROM site_status WHERE site = $1"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, site)

    async def delete_user_blacklisted_words(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "DELETE FROM blacklisted_words WHERE user_id = $1"

        async with self.pool.acquire() as con:
            await con.execute(sql, user_id)

    async def update_ticket(
        self, ticket_id, ticket_status, support_chat_id, support_username
    ):
        try:
            await detect_sql_injection(ticket_id, support_chat_id)
            await detect_sql_injection(ticket_status, support_chat_id)
            await detect_sql_injection(support_chat_id, support_chat_id)
            await detect_sql_injection(support_username, support_chat_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """
        UPDATE tickets 
        SET 
            ticket_status = $1, 
            support_username = $2, 
            support_chat_id = $3 
        WHERE id = $4
        """

        async with self.pool.acquire() as con:
            await con.execute(
                sql, ticket_status, support_username, support_chat_id, int(ticket_id)
            )

    async def get_ticket_info(self, ticket_id):
        try:
            await detect_sql_injection(ticket_id, ticket_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "SELECT owner_chat_id, ticket_status, support_chat_id, ticket_detail FROM tickets WHERE id = $1"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, int(ticket_id))

    async def update_ticket_status(self, ticket_id, ticket_status):
        try:
            await detect_sql_injection(ticket_id, ticket_id)
            await detect_sql_injection(ticket_status, ticket_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "UPDATE tickets SET ticket_status = $1 WHERE id = $2"

        async with self.pool.acquire() as con:
            await con.execute(sql, ticket_status, int(ticket_id))

    async def add_user(self, user_id, username):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(username, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """
        INSERT INTO bot_users(user_id, username) VALUES($1, $2) 
        ON CONFLICT (user_id) DO UPDATE SET username = $2 WHERE bot_users.user_id = $1
        """

        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, username)

    async def get_username_by_id(self, chat_id):
        try:
            await detect_sql_injection(chat_id, chat_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "SELECT username FROM bot_users WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, chat_id)

    async def update_user_refer(self, user_id: int, referrer_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(referrer_id, referrer_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "UPDATE bot_users SET referrer_id = $1 WHERE user_id = $2"
        async with self.pool.acquire() as con:
            await con.execute(sql, referrer_id, user_id)

    async def get_user(self, chat_id):
        try:
            await detect_sql_injection(chat_id, chat_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT * FROM bot_users WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, int(chat_id))

    async def get_referrals_count(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT COUNT(*) FROM bot_users WHERE referrer_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def get_user_referral_days(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT referral_days FROM bot_users WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def set_referral_days(self, user_id, days):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(days, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "UPDATE bot_users SET referral_days=$1 WHERE user_id=$2"

        async with self.pool.acquire() as con:
            await con.execute(sql, days, user_id)

    async def add_payment_info(self, payment_id, username, user_id, status):
        try:
            await detect_sql_injection(payment_id, user_id)
            await detect_sql_injection(username, user_id)
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(status, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO payment_info(payment_id, username, user_id, status) VALUES($1, $2, $3, $4)"
        async with self.pool.acquire() as con:
            return await con.execute(
                sql, int(payment_id), username, str(user_id), status
            )

    async def get_payment_status(self, user_id, payment_id):
        try:
            await detect_sql_injection(payment_id, user_id)
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "SELECT status FROM payment_info WHERE user_id = $1 AND payment_id = $2"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, str(user_id), int(payment_id))

    async def update_payment_status(self, user_id, payment_id, status):
        try:
            await detect_sql_injection(payment_id, user_id)
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(status, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = (
            "UPDATE payment_info SET status = $1 WHERE user_id = $2 AND payment_id = $3"
        )
        async with self.pool.acquire() as con:
            await con.execute(sql, status, str(user_id), int(payment_id))

    async def get_user_referral_by_id(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """SELECT referrer_id FROM bot_users WHERE user_id = $1"""
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def add_payment_stat(self, admin_id, username, place, days_amount):
        try:
            await detect_sql_injection(admin_id, username)
            await detect_sql_injection(username, username)
            await detect_sql_injection(place, username)
            await detect_sql_injection(days_amount, username)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "INSERT INTO payments_stats(admin_id, username, place, days_amount) VALUES($1, $2, $3, $4) RETURNING id"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, admin_id, username, place, int(days_amount))

    async def get_user_features(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "SELECT site FROM site_features WHERE user_id = $1"
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id)

    async def add_user_feature(self, user_id, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "INSERT INTO site_features(user_id, site) VALUES($1, $2)"
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site)

    async def delete_user_feature(self, user_id, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "DELETE FROM site_features WHERE user_id = $1 AND site = $2"
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site)

    async def get_last_change_date(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "SELECT MAX(change_date) FROM subscription_change_history WHERE user_id = $1"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def check_if_user_has_parsed_after_date(self, user_id, date, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(date, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """SELECT EXISTS (
                SELECT 1
                FROM parser_history
                WHERE user_id = $1 AND site = $2 AND record_date > $3)"""
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id, site, date)

    async def add_change_history(
        self,
        user_id,
        old_platform,
        new_platform,
        old_subscription_period,
        new_subscription_period,
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(old_platform, user_id)
            await detect_sql_injection(new_platform, user_id)
            await detect_sql_injection(old_subscription_period, user_id)
            await detect_sql_injection(new_subscription_period, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO subscription_change_history(user_id, old_platform, new_platform, old_subscription_period, new_subscription_period) VALUES($1, $2, $3, $4, $5)"
        async with self.pool.acquire() as con:
            await con.execute(
                sql,
                user_id,
                old_platform,
                new_platform,
                old_subscription_period,
                new_subscription_period,
            )

    async def update_timezone(self, user_id, timezone):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(timezone, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "UPDATE bot_users SET timezone = $1 WHERE user_id = $2"
        async with self.pool.acquire() as con:
            await con.execute(sql, timezone, user_id)

    async def get_timezone(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT timezone FROM bot_users WHERE user_id = $1"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def get_custom_msg_text(self, user_id: int, site: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """
        SELECT text_title, text_body FROM user_custom_text WHERE user_id = $1 AND site = $2
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, int(user_id), site)

    async def delete_custom_msg_text(self, user_id: int, site: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        DELETE FROM user_custom_text WHERE user_id = $1 AND site = $2
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site)

    async def delete_all_user_presets(self, user_id: int, site: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        DELETE FROM user_presets WHERE user_id = $1 AND site = $2
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site)

    async def delete_custom_msg_text_by_title(
        self, user_id: int, site: str, text_title
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(text_title, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        DELETE FROM user_custom_text WHERE user_id = $1 AND site = $2 AND text_title = $3
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site, text_title)

    async def add_custom_msg_text(self, user_id, text_title, text_body, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(text_title, user_id)
            await detect_sql_injection(text_body, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        async with self.pool.acquire() as con:
            sql = """
            INSERT INTO user_custom_text (user_id, text_title, text_body, site) 
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, text_title, site)
            DO UPDATE SET text_body = EXCLUDED.text_body
            """
            await con.execute(sql, user_id, text_title, quote_plus(text_body), site)

    async def get_custom_msg_text_by_title(
        self, user_id: int, site: str, text_title: str
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(text_title, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """
        SELECT text_body FROM user_custom_text WHERE user_id = $1 AND site = $2 AND text_title = $3
        """
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, int(user_id), site, text_title)

    async def get_presets(self, user_id: int, site: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT text_title, text_body FROM user_presets WHERE user_id = $1 AND site = $2
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, site)

    async def get_id_by_username(self, username):
        try:
            await detect_sql_injection(username, username)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT user_id FROM bot_users WHERE username = $1"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, username)

    async def count_user_referrals(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT COUNT(user_id) FROM bot_users WHERE referrer_id = $1"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def get_all_users_id(self):
        sql = "SELECT user_id FROM bot_users"
        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def get_payments(self, days):
        try:
            await detect_sql_injection(days, days)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = f"SELECT place, days_amount, id FROM payments_stats WHERE DATE(date) >= CURRENT_DATE AND DATE(date) < CURRENT_DATE + INTERVAL '{days} DAY' "
        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def get_payments_by_word(self, word):
        try:
            await detect_sql_injection(word, word)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = f"SELECT place, days_amount, id FROM payments_stats WHERE date >= date_trunc('{word}', CURRENT_DATE);"
        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def get_tp_ban_status(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "SELECT is_tp_banned FROM bot_users WHERE user_id = $1"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def set_tp_ban_status_user(self, user_id, status):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(status, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = "UPDATE bot_users SET is_tp_banned = $1 WHERE user_id = $2"
        async with self.pool.acquire() as con:
            await con.execute(sql, status, user_id)

    async def delete_payment(self, row_id):
        try:
            await detect_sql_injection(row_id, row_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        DELETE FROM payments_stats WHERE id = $1
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, row_id)

    async def get_user_saved_keyword(self, user_id, site, save_type):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(save_type, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT keyword FROM user_word_complete WHERE user_id = $1 AND site = $2 AND save_type = $3"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id, site, save_type)

    async def save_user_keyword(self, user_id, keyword, site, save_type):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(keyword, user_id)
            await detect_sql_injection(save_type, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql_upsert = """
        INSERT INTO user_word_complete(user_id, keyword, site, save_type) VALUES($1, $2, $3, $4)
        ON CONFLICT (user_id, site, save_type) DO UPDATE SET keyword = EXCLUDED.keyword;
        """

        async with self.pool.acquire() as con:
            await con.execute(sql_upsert, user_id, keyword, site, save_type)

    async def add_preset(self, user_id, text_body, text_title, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(text_title, user_id)
            await detect_sql_injection(text_body, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO user_presets (user_id, text_body, text_title, site, share_id) VALUES($1, $2, $3, $4, $5)"
        async with self.pool.acquire() as con:
            await con.execute(
                sql,
                user_id,
                text_body,
                text_title,
                site,
                str(uuid.uuid4()).replace("-", ""),
            )

    async def get_user_presets_by_title(self, user_id: int, site: str, text_title: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(text_title, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT text_body, share_id FROM user_presets WHERE user_id = $1 AND site = $2 AND text_title = $3
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, site, text_title)

    async def get_user_last_parser(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT text_body, share_id FROM user_presets WHERE user_id = $1 AND text_title = 'last_parser' ORDER BY id DESC LIMIT 1
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id)

    async def delete_user_preset_by_title(self, user_id: int, site: str, text_title):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(text_title, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        DELETE FROM user_presets WHERE user_id = $1 AND site = $2 AND text_title = $3
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site, text_title)

    async def delete_user_last_parser(self, user_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """
        DELETE FROM user_presets WHERE user_id = $1 AND text_title = 'last_parser'
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id)

    async def get_preset_by_shared_id(self, share_id):
        try:
            await detect_sql_injection(share_id, share_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """
        SELECT text_body, text_title, site FROM user_presets WHERE share_id = $1
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, share_id)

    async def get_saved_user_links(self, user_id, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """SELECT id, link FROM user_saved_links WHERE user_id = $1 AND site = $2 ORDER BY date DESC LIMIT 3 """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, site)

    async def save_user_link(self, user_id, site, link):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(link, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        async with self.pool.acquire() as con:
            sql = (
                "INSERT INTO user_saved_links (user_id, site, link) VALUES ($1, $2, $3)"
            )
            await con.execute(sql, user_id, site, link)

    async def get_saved_user_links_by_id(self, row_id):
        try:
            await detect_sql_injection(row_id, row_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return
        sql = """SELECT link FROM user_saved_links WHERE id= $1"""
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, row_id)

    async def add_parser_history(
        self,
        user_id: int,
        stat_id: int,
        person_id: str,
        title: str,
        price: str,
        creation_date: str,
        ad_link: str,
        site: str,
        rating: int = None,
        location: str = "",
        person_name: str = "",
        views: int = None,
        description: str = "",
        gender: str = "",
        ads_number: int = None,
        delivery: str = "",
        possible_phones: str = "",
        photo: str = "",
        person_registration_date: str = "",
        email: str = "",
        person_link: str = "",
        phone: str = "",
        ads_number_buyed: int = None,
        ads_number_selled: int = None,
        our_views: int = 0,
        success_delivery_count: int = None,
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(person_name, user_id)
            await detect_sql_injection(phone, user_id)
            await detect_sql_injection(success_delivery_count, user_id)
            await detect_sql_injection(ads_number_buyed, user_id)
            await detect_sql_injection(our_views, user_id)
            await detect_sql_injection(ads_number_selled, user_id)
            await detect_sql_injection(person_link, user_id)
            await detect_sql_injection(email, user_id)
            await detect_sql_injection(person_registration_date, user_id)
            await detect_sql_injection(possible_phones, user_id)
            await detect_sql_injection(photo, user_id)
            await detect_sql_injection(views, user_id)
            await detect_sql_injection(ads_number, user_id)
            await detect_sql_injection(delivery, user_id)
            # await detect_sql_injection(description, user_id)
            await detect_sql_injection(stat_id, user_id)
            await detect_sql_injection(person_id, user_id)
            await detect_sql_injection(ad_link, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(rating, user_id)
            await detect_sql_injection(location, user_id)
            # await detect_sql_injection(title, user_id)
            await detect_sql_injection(price, user_id)
            await detect_sql_injection(creation_date, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        if str(rating).replace("00", "0").replace(".", "").isdigit():
            rating = int(str(rating).replace("00", "0").replace(".", ""))
        if rating == "N/A":
            rating = None

        if str(ads_number).isdigit():
            ads_number = int(ads_number)
        if ads_number == "N/A":
            ads_number = None

        if str(views).isdigit():
            views = int(views)
        if views == "N/A":
            views = None
        if gender == "N/A":
            gender = None

        if price is None:
            price = "N/A"

        if str(success_delivery_count).isdigit():
            success_delivery_count = int(success_delivery_count)
        if success_delivery_count == "N/A":
            success_delivery_count = None

        if str(ads_number_buyed).isdigit():
            ads_number_buyed = int(ads_number_buyed)
        if ads_number_buyed == "N/A":
            ads_number_buyed = None

        if str(ads_number_selled).isdigit():
            ads_number_selled = int(ads_number_selled)
        if ads_number_selled == "N/A":
            ads_number_selled = None

        sql = """
        INSERT INTO parser_history (user_id, stat_id, title, price, location, creation_date, 
        views, ad_link, person_name,
        rating,person_id, site, description, ads_number, delivery, possible_phones, photo, person_registration_date, email, person_link, phone, ads_number_buyed, ads_number_selled, our_views, success_delivery_count, gender) 
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10 , $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26)
        """
        async with self.pool.acquire() as con:
            await con.execute(
                sql,
                user_id,
                stat_id,
                title,
                price,
                str(location),
                creation_date,
                views,
                ad_link,
                person_name,
                rating,
                str(person_id),
                site,
                description,
                ads_number,
                delivery,
                str(possible_phones),
                photo,
                person_registration_date,
                email,
                person_link,
                phone,
                ads_number_buyed,
                ads_number_selled,
                our_views,
                success_delivery_count,
                gender,
            )

    async def get_user_parser_history(self, user_id: int, stat_id: str):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT * FROM parser_history WHERE user_id = $1 AND stat_id = $2
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, stat_id)

    async def get_user_parser_history_offset(
        self, user_id: int, stat_id: str, offset: int
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
            await detect_sql_injection(offset, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT * FROM parser_history 
        WHERE user_id = $1 AND stat_id = $2 
        OFFSET $3
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, stat_id, offset)

    async def add_stats_ticker(
        self, user_id: int, stat_id: int, site: str, last_msg: str
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(stat_id, user_id)
            await detect_sql_injection(last_msg, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        INSERT INTO stats_ticker (user_id, stat_id, site, last_msg) VALUES ($1, $2, $3, $4)
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, stat_id, site, last_msg)

    async def get_all_stats_tickers(self):
        sql = """
        SELECT * FROM stats_ticker
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def add_parser_stats_history(
        self,
        user_id: int,
        stat_id: int,
        site: str,
        error_code: str,
        error_details: str,
    ):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(stat_id, user_id)
            await detect_sql_injection(error_code, user_id)
            await detect_sql_injection(error_details, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        INSERT INTO parser_stats_history (user_id, stat_id, site, error_code, error_details) VALUES ($1, $2, $3, $4, $5)
        """
        async with self.pool.acquire() as con:
            await con.execute(
                sql, user_id, stat_id, site, error_code, str(error_details)
            )

    async def get_parser_stats_history(self, user_id: int, stat_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT error_code FROM parser_stats_history WHERE user_id = $1 AND stat_id = $2
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, stat_id)

    async def get_parser_stats_history_with_links(self, user_id: int, stat_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        SELECT error_code, error_details FROM parser_stats_history WHERE user_id = $1 AND stat_id = $2
        """
        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, stat_id)

    async def get_count_received_item(self, user_id: int, stat_id: int):
        # try:
        #     await detect_sql_injection(user_id, user_id)
        #     await detect_sql_injection(stat_id, user_id)
        # except ValueError as e:
        #     logger.debug(f"Potential SQL injection detected: {e}")
        #     return

        sql2 = """
        SELECT COUNT(*) FROM parser_history WHERE user_id = $1 and stat_id = $2
        """
        async with self.pool.acquire() as con:
            return await con.fetchval(sql2, user_id, stat_id)

    async def remove_stats_ticker(self, user_id: int, stat_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        DELETE FROM stats_ticker WHERE user_id = $1 AND stat_id = $2
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, stat_id)

    async def add_run_stats(self, site, keyword):
        try:
            await detect_sql_injection(keyword, keyword)
            await detect_sql_injection(site, keyword)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO run_stats(site, keyword) VALUES($1, $2)"

        async with self.pool.acquire() as con:
            await con.execute(sql, site, keyword.casefold())

    async def get_link_run_stats(self, site):
        try:
            await detect_sql_injection(site, site)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT keyword FROM run_stats WHERE site = $1 AND DATE(date) >= CURRENT_DATE AND DATE(date) < CURRENT_DATE + INTERVAL '1 DAY' "
        async with self.pool.acquire() as con:
            return await con.fetch(sql, site)

    async def get_last_run_date(self, site, keyword):
        try:
            await detect_sql_injection(keyword, keyword)
            await detect_sql_injection(site, keyword)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT date FROM run_stats WHERE site = $1 AND DATE(date) >= CURRENT_DATE AND DATE(date) < CURRENT_DATE + INTERVAL '1 DAY' AND keyword = $2 ORDER BY date DESC"
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, site, keyword)

    async def get_avg_for_column(self, site: str, column: str, days: int):
        ...
        # interval = timedelta(days=days)
        # sql = (
        #     f"SELECT DISTINCT ON (ad_link) {column}, record_date "
        #     f"FROM parser_history "
        #     f"WHERE site = $1 AND record_date >= current_date - $2::interval "
        #     f"ORDER BY ad_link, {column} DESC, record_date DESC"
        # )
        #
        # async with self.pool.acquire() as con:
        #     return await con.fetch(sql, site, interval)

    async def get_avg_for_column_with_person_id(
        self, site: str, column: str, days: int
    ):
        ...
        # interval = timedelta(days=days)
        # sql = (
        #     f"SELECT {column}, person_id, record_date FROM parser_history "
        #     f"WHERE site = $1 AND record_date >= current_date - $2::interval"
        # )
        #
        # async with self.pool.acquire() as con:
        #     return await con.fetch(sql, site, interval)

    async def get_error_details_stats(self, site: str, error_code: str, days: int):
        try:
            await detect_sql_injection(error_code, site)
            await detect_sql_injection(days, site)
            await detect_sql_injection(site, site)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        interval = timedelta(days=days)
        sql = "SELECT error_details, record_date FROM parser_stats_history WHERE site = $1 AND error_code = $2 AND record_date >= current_date - $3::interval"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, site, error_code, interval)

    async def get_old_stats_id_editor(self, minutes: int):
        try:
            await detect_sql_injection(minutes, minutes)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = f"SELECT user_id, stat_id FROM stats_ticker WHERE date < CURRENT_TIMESTAMP - INTERVAL '{minutes} minutes'"

        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def update_date_stats_ticker(self, user_id: int, stat_id: int):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "UPDATE stats_ticker SET date = CURRENT_TIMESTAMP WHERE user_id = $1 AND stat_id = $2"

        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, stat_id)

    async def get_stats_id_by_user_id(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT stat_id FROM stats_ticker WHERE user_id = $1"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id)

    async def get_all_stats_id_by_user_id(self, user_id, stat_id):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(stat_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT * FROM stats_ticker WHERE user_id = $1 AND stat_id = $2"

        async with self.pool.acquire() as con:
            return await con.fetch(sql, user_id, stat_id)

    async def add_item_id_to_worker_views(self, user_id, site, item_id):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(item_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO worker_views(user_id, site, item_id) VALUES($1, $2, $3)"

        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site, str(item_id))

    async def get_worker_views_count(self, item_id, site):
        try:
            await detect_sql_injection(item_id, item_id)
            await detect_sql_injection(site, item_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT COUNT(DISTINCT user_id) FROM worker_views WHERE item_id = $1 AND site = $2"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, str(item_id), site)

    async def is_person_id_blacklisted_user_shared(self, site: str, person_id):
        try:
            await detect_sql_injection(site, person_id)
            await detect_sql_injection(site, person_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT blacklisted_id FROM blacklist_persons WHERE site = $1 AND blacklisted_id = $2"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, site, str(person_id))

    async def is_person_id_blacklisted_user(self, user_id: int, site: str, person_id):
        try:
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(person_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT blacklisted_id FROM blacklist_persons WHERE user_id = $1 AND site = $2 AND blacklisted_id = $3"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id, site, str(person_id))

    async def add_person_id_to_blacklist(self, user_id, site, blacklisted_id):
        try:
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(blacklisted_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO blacklist_persons(user_id, site, blacklisted_id) VALUES($1, $2, $3)"

        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, site, str(blacklisted_id))

    async def get_items_for_sender(self, stat_id: int):
        try:
            await detect_sql_injection(stat_id, stat_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """SELECT ad_link, person_name, price, title FROM parser_history WHERE stat_id = $1"""

        async with self.pool.acquire() as con:
            return await con.fetch(sql, int(stat_id))

    async def set_new_preset_body(self, user_id, site, text_title, text_body):
        try:
            await detect_sql_injection(site, user_id)
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(text_title, user_id)
            await detect_sql_injection(text_body, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "UPDATE user_presets SET text_body=$1 WHERE text_title=$2 AND user_id = $3 AND site = $4"
        async with self.pool.acquire() as con:
            await con.execute(sql, text_body, text_title, user_id, site)

    async def get_wa_credits(self, tg_user_id, days):
        try:
            await detect_sql_injection(tg_user_id, tg_user_id)
            await detect_sql_injection(days, tg_user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = f"SELECT COUNT(*) FROM wa_credits WHERE user_id = $1 AND DATE(date) >= CURRENT_DATE AND DATE(date) < CURRENT_DATE + INTERVAL '{days} DAY' "
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, str(tg_user_id))

    async def add_wa_credits(self, user_id):
        try:
            await detect_sql_injection(user_id, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "INSERT INTO wa_credits(user_id) VALUES($1)"

        async with self.pool.acquire() as con:
            await con.execute(sql, str(user_id))

    async def add_user_tokens(self, tokens, site, chat_id):
        try:
            await detect_sql_injection(tokens, chat_id)
            await detect_sql_injection(chat_id, chat_id)
            await detect_sql_injection(site, chat_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = """
        INSERT INTO user_tokens(tokens, site, chat_id) 
        VALUES($1, $2, $3) 
        ON CONFLICT(chat_id, site) 
        DO UPDATE SET tokens = EXCLUDED.tokens
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, tokens, site, chat_id)

    async def get_user_tokens(self, user_id: int, site):
        try:
            await detect_sql_injection(user_id, user_id)
            await detect_sql_injection(site, user_id)
        except ValueError as e:
            logger.debug(f"Potential SQL injection detected: {e}")
            return

        sql = "SELECT tokens FROM user_tokens WHERE chat_id = $1 AND site = $2"

        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id, site)

    async def get_stats_id_where_old_msg_enable(self):
        sql = """SELECT st.user_id, st.stat_id
FROM stats_ticker st
JOIN user_settings us ON st.user_id = us.user_id
WHERE us.old_msg_send = TRUE;
"""
        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def add_throttled_proxy(self, proxy, site):
        sql = """INSERT INTO throttling_control_proxy (proxy, site) VALUES ($1, $2)"""
        async with self.pool.acquire() as con:
            await con.execute(sql, proxy, site)

    async def add_throttled_proxy_v2(self, proxy, site):
        sql = """INSERT INTO  throttling_control_proxy(proxy, status, site) VALUES ($1, $2, $3)"""
        async with self.pool.acquire() as con:
            await con.execute(sql, proxy, "throttled", site)

    async def remove_throttled_proxy(self, proxy, site):
        sql = """DELETE FROM throttling_control_proxy WHERE proxy = $1 and site = $2"""
        async with self.pool.acquire() as con:
            await con.execute(sql, proxy, site)

    async def get_in_use_proxy(self, site):
        sql = """SELECT proxy FROM throttling_control_proxy WHERE site = $1"""
        async with self.pool.acquire() as con:
            records = await con.fetch(sql, site)
            return [record["proxy"] for record in records]

    async def get_blacklist_proxy(self):
        sql = """SELECT proxy FROM proxy_manager_blacklist"""
        async with self.pool.acquire() as con:
            records = await con.fetch(sql)
            return [record["proxy"] for record in records]

    async def remove_blacklist_proxy(self, proxy):
        sql = """DELETE FROM proxy_manager_blacklist WHERE proxy = $1"""
        async with self.pool.acquire() as con:
            await con.execute(sql, proxy)

    async def add_blacklist_proxy(self, proxy):
        sql = """INSERT INTO proxy_manager_blacklist(proxy) VALUES ($1)"""
        async with self.pool.acquire() as con:
            await con.execute(sql, proxy)

    async def get_throttled_proxy(self):
        sql = """SELECT proxy, site FROM throttling_control_proxy WHERE status = 'throttled' AND CURRENT_TIMESTAMP - throttled_date >= interval '1 minute' """
        async with self.pool.acquire() as con:
            return await con.fetch(sql)

    async def get_user_parser_status(self, user_id):
        sql = """SELECT status FROM user_parser_status WHERE user_id = $1"""
        async with self.pool.acquire() as con:
            return await con.fetchval(sql, user_id)

    async def add_parser_status(self, user_id, status):
        sql = """
        INSERT INTO user_parser_status(user_id, status) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE
        SET status = EXCLUDED.status;
        """
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, status)

    async def remove_running_parser_recovery_info(self, user_id):
        sql = """DELETE FROM running_parser_recovery_info WHERE chat_id = $1"""
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id)

    async def add_running_parser_recovery_info(self, user_id, info):
        sql = """INSERT INTO running_parser_recovery_info(chat_id, info) VALUES ($1, $2)"""
        async with self.pool.acquire() as con:
            await con.execute(sql, user_id, info)

    async def get_running_parser_recovery_info(self):
        sql = """SELECT info FROM running_parser_recovery_info"""
        async with self.pool.acquire() as con:
            return await con.fetch(sql)
