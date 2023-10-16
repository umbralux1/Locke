from loguru import logger

from .errors import error_handler

from . import start
from . import start_parsing_menu
from . import referral_system
from . import site_actions
from . import start_parsing
from . import format_result


from . import site_actions_misc
from .site_actions_misc import features_control, custom_text, presets
from .site_actions_misc import change_sub

from .payments import referral_buy
from .payments import crypto_bot
from .payments import buy_sub
from .payments import anypay
from .payments import payok

from .settings_system import settings
from .settings_system import settings_btns
from .settings_system import ads_limit
from .settings_system import blacklist_ads
from .settings_system import blacklist_words

# желательно это все самым последним держать
from .help_system import ticket_getter
from .help_system import ticket_proccessing

from .commands import timezone_selector

from .admin_actions import admin
from .admin_actions import get_user
from .admin_actions import cash_report
from .admin_actions import mailer
from .admin_actions import change_site_status
from .admin_actions import add_ref_days
from .admin_actions import sub_manipulator
from .admin_actions import proxy_check
from .admin_actions import site_checker

from .sites.anibis_ch import anibis_handler
from .sites.willhaben import willhaben_handler

from .senders import sender_selector

logger.info("Handlers are successfully configured")
