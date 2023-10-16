from contextlib import suppress
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from app import dp, db
from app.config import CHATS
from app.keyboards.all_sites_menu import (
    get_better_pages_keyboard,
    make_place_pretty_view,
    Pagination,
    ShowSite,
)
from app.keyboards.quick_transition_to_site import get_place_access_btns
from app.misc.time_declension import humanize_date_v2, humanize_date
from app.misc.timezone_mapping import convert_to_user_timezone
from app.sites_config import sorted_sites, sites

router = Router()
dp.include_router(router)


@router.callback_query(F.data.contains("change_sub"))
async def change_sub(query: CallbackQuery, state: FSMContext):
    site = query.data.split("|")[-1]
    user_id = query.from_user.id
    expire_date = await db.get_user_subscription_site(site=site, user_id=user_id)
    seconds_left = (expire_date - datetime.now()).total_seconds()

    if seconds_left < 90000:
        await query.message.answer(
            "❌ У вас осталось меньше чем 25ч подписки, нельзя менять площадку! (тк.к при смене будет вычетаться 1 день)"
        )
        return

    text = (
        "<i>• Подписка уменьшится на 1 день.\n• Запрет на смену подписки на 2 дня.</i>"
    )
    await state.update_data(kd=True)

    last_change_date = await db.get_last_change_date(user_id=user_id)
    if last_change_date:
        time_since_last_change = datetime.now() - last_change_date
        has_parsed_after_last_change = await db.check_if_user_has_parsed_after_date(
            user_id=user_id, date=last_change_date, site=site
        )

        can_change_now = True  # По умолчанию разрешаем смену площадки
        time_frame = None  # Храним ограничение по времени

        if has_parsed_after_last_change:
            if time_since_last_change < timedelta(days=2):
                can_change_now = False
                time_frame = "2 дня"
        elif time_since_last_change < timedelta(minutes=15):
            can_change_now = False
            time_frame = "15 минут"

        if not can_change_now:
            remaining_time = humanize_date(
                last_change_date
                + (
                    timedelta(days=2)
                    if time_frame == "2 дня"
                    else timedelta(minutes=15)
                ),
                add_word=False,
            )
            await query.message.answer(
                f"❌ Вы не можете менять подписку раньше чем раз в {time_frame}!\n\nВы сможете сменить площадку через: {remaining_time}"
            )
            return
    else:
        has_parsed_after_last_change = await db.check_if_user_has_parsed_after_date(
            user_id=user_id, date=datetime.now() - timedelta(days=30), site=site
        )

    # logger.debug(has_parsed_after_last_change)
    if not has_parsed_after_last_change:
        await state.update_data(kd=False)
        text = "<i>• Подписка не уменьшится, тк.к вы не парсили</i>"

    await state.update_data(current_place=site)
    await query.message.edit_caption(
        caption=f"""<b>⚠️ Важно, при смене площадки:</b>\n\n{text}\n\n❓ Выберите площадку для замены.""",
        reply_markup=get_better_pages_keyboard(
            sorted_sites,
            page=1,
            is_feature=True,
            search_place=True,
            show_key="change_site",
        ),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(Pagination.filter(F.show_key == "change_site"))
async def pagination_change_menu(query: CallbackQuery, callback_data: Pagination):
    with suppress(ValueError, TelegramAPIError):
        current_page = int(callback_data.page)
        await query.message.edit_reply_markup(
            reply_markup=get_better_pages_keyboard(
                sorted_sites,
                page=current_page,
                is_feature=True,
                search_place=True,
                show_key="change_site",
            ),
        )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(ShowSite.filter(F.show_key == "change_site"))
async def change_site(query: CallbackQuery, callback_data: ShowSite, state: FSMContext):
    site = callback_data.site
    state_data = await state.get_data()
    current_place = state_data.get("current_place")

    # Если текущая подписка совпадает с выбранной
    if current_place == site:
        await query.message.answer("❌ Вы уже имеете подписку данной площадки")
        return

    # Определение доступности подписки
    current_site_info = sites.get(current_place)
    target_site_info = sites.get(site)

    if not current_site_info.get("is_changeable") and target_site_info.get(
        "is_changeable"
    ):
        await query.message.answer(
            "❌ Нельзя сменить подписку на выбранную площадку, так как текущая площадка дешевле\n\n<a href='https://telegra.ph/1'>Почему не на все площадки можно перенести подписку или купить за реферальные дни?</a>"
        )
        return

    if not target_site_info.get("can_give_for_free"):
        await query.message.answer(
            "❌ Нельзя сменить подписку на выбранную площадку\n\n<a href='https://telegra.ph/1'>Почему не на все площадки можно перенести подписку или купить за реферальные дни?</a>"
        )
        return

    # Рассчет даты окончания подписки
    expire_date_current_place = await db.get_user_subscription_site(
        site=current_place,
        user_id=query.from_user.id,
    )

    expire_date_site = await db.get_user_subscription_site(
        site=site,
        user_id=query.from_user.id,
    )

    if expire_date_site:
        seconds_left = (expire_date_site - datetime.now()).total_seconds()
        new_end_date = (
            expire_date_current_place
            + timedelta(seconds=seconds_left)
            - timedelta(hours=24)
        )
    else:
        new_end_date = expire_date_current_place - timedelta(hours=24)

    text = """<i>Подписка уменьшится на 1 день</i>
<i>Запрет на смену подписки: 2 дня</i>"""
    is_kd = state_data.get("kd")
    if not is_kd:
        text = "<i>Подписка не уменьшится, тк.к вы не парсили</i>"

    await query.message.edit_caption(
        caption=f"""
<b>🔄 Меняем подписку:</b>
{make_place_pretty_view(current_place)} ⟶ {make_place_pretty_view(site)}

<b>⚠️ Учет при смене:</b>
{text}

<b>📅 Новая дата окончания:</b>
<i>{humanize_date_v2(await convert_to_user_timezone(new_end_date, user_id=query.from_user.id))}</i>
    """,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Перенести",
                        callback_data=f"site_change_confirmed|{current_place}|{site}|{is_kd}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Отмена", callback_data="cancel_action"
                    ),
                ],
            ]
        ),
    )

    await state.clear()

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data.contains("site_change_confirmed"))
async def site_change_confirmed(query: CallbackQuery, state: FSMContext):
    current_place = query.data.split("|")[-3]
    site = query.data.split("|")[-2]
    is_kd = query.data.split("|")[-1]

    expire_date_current_place = await db.get_user_subscription_site(
        site=current_place,
        user_id=query.from_user.id,
    )

    if is_kd == "True":
        new_end_date = expire_date_current_place - timedelta(hours=24)
    else:
        new_end_date = expire_date_current_place

    await query.bot.send_message(
        chat_id=CHATS.get("logs"),
        text=f"""
#change

▶️ Взял: <b>{query.from_user.mention_html()} / {query.from_user.id} / {query.from_user.username} </b>

▶️ Сменил с: <b>{make_place_pretty_view(current_place)}</b>
▶️ На: <b>{make_place_pretty_view(site)}</b>

▶️ Время подписки было: <b>{expire_date_current_place.strftime('%d.%m.%Y %H:%M')}</b>
▶️ Время подписки стало: <b>{new_end_date.strftime('%d.%m.%Y %H:%M')}</b>
""",
    )
    await db.add_change_history(
        query.from_user.id,
        current_place,
        site,
        expire_date_current_place,
        new_end_date,
    )

    await db.add_subscription(
        site=site,
        new_expiry_date=new_end_date,
        user_id=query.from_user.id,
    )
    await db.remove_subscription(
        site=current_place,
        user_id=query.from_user.id,
    )

    await query.message.edit_caption(
        caption="✅ Подписка успешно перенесена",
        reply_markup=get_place_access_btns(site),
    )
