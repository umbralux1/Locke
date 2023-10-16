import traceback
from contextlib import suppress

from aiogram import types, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from app import dp, db, redis
from app.config import CHATS, LIMIT_MAX_PRESETS, SENDER_STATUS_DB
from app.filters.private_chat import IsPrivate
from app.filters.username import IsUserHasUsername
from app.handlers.commands.timezone_selector import select_timezone
from app.keyboards.all_sites_menu import make_place_pretty_view
from app.keyboards.start_menu_markup import get_start_menu_markup

router = Router()
dp.include_router(router)

flags = {"throttling_key": "default"}


@router.message(CommandStart(), IsPrivate(), IsUserHasUsername(), flags=flags)
async def start_handler(msg: types.Message, state: FSMContext):
    await state.clear()

    await db.add_user(user_id=msg.from_user.id, username=msg.from_user.username)
    await db.init_user_settings(user_id=msg.from_user.id)
    await msg.answer(
        "Добро пожаловать!\n\n<a href='https://telegra.ph/1'>Очень важно, прочитать перед использованием</a>",
        reply_markup=get_start_menu_markup(msg.from_user.id),
    )

    msg_args = msg.text.split()[-1]

    if not await db.get_timezone(msg.from_user.id):
        await select_timezone(msg)

    if msg_args and "REF" in msg_args:
        refer_id = msg_args.replace("REF", "")
        if not refer_id.isdigit():
            await msg.answer("❌ Неверный код")
            return

        refer_username = await db.get_username_by_id(int(refer_id))
        if refer_username is None:
            await msg.answer("❌ Пользователь не найден")
            return

        await msg.answer(
            f"Вы точно хотите стать рефералом пользователя @{await db.get_username_by_id(int(refer_id))}/ID-{refer_id}?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Да", callback_data=f"confirm_referral|{refer_id}"
                        )
                    ],
                ]
            ),
        )
    elif msg_args and "CFG" in msg_args:
        shared_cfg = msg_args.replace("CFG", "")
        configuration_settings = await db.get_configuration_settings(
            user_id=msg.from_user.id
        )
        configuration_settings = configuration_settings[0]
        configuration_settings_keys = list(configuration_settings.keys())
        configuration_settings_keys.remove("user_id")
        configuration_settings_keys.remove("getter_ads_limit")
        # logger.debug(configuration_settings_keys)

        # logger.debug(len(configuration_settings_keys))
        # logger.debug(len(shared_cfg))
        if len(configuration_settings_keys) != len(shared_cfg):
            await msg.answer("❌ Неверный код")
            return

        for name, value in zip(configuration_settings_keys, shared_cfg):
            try:
                numeric_value = int(value)
            except ValueError:
                await msg.answer("❌ Неверный код")
                return

            if numeric_value == 1:
                await db.update_user_setting(msg.from_user.id, name, True)
            elif numeric_value == 0:
                await db.update_user_setting(msg.from_user.id, name, False)
            elif numeric_value in {2, 3}:
                try:
                    await db.update_user_setting(msg.from_user.id, name, numeric_value)
                except Exception:
                    await msg.answer(
                        "❌ Что-то пошло не так, возможно неверный код, обратитесь в тп за помощью"
                    )
                    return

        await msg.answer("✅ Конфигурация успешно установлена")
    elif msg_args and "reply-" in msg_args:
        await msg.bot.send_message(
            msg.from_user.id,
            "Нажмите кнопку проверить оплату",
            reply_to_message_id=msg_args.split("reply-")[-1],
        )
    elif msg_args and "PRESET" in msg_args:
        shared_preset = msg_args.replace("PRESET", "")
        preset = await db.get_preset_by_shared_id(shared_preset)
        if not preset:
            await msg.answer("❌ Неверный код или пресет уже удален")
            return
        preset = preset[0]

        user_presets = await db.get_presets(
            site=preset.get("site"), user_id=msg.from_user.id
        )
        if user_presets:
            all_presets = user_presets[0].get("text_title")
            if preset.get("text_title") in str(all_presets):
                await msg.answer(
                    f"❌ У вас уже есть пресет с именем {preset.get('text_title')}"
                )
                return

        if len(user_presets) >= LIMIT_MAX_PRESETS:
            await msg.answer(
                "❌ Пресет не был сохранен, так как лимит исчерпан",
            )
            return

        await db.add_preset(user_id=msg.from_user.id, **preset)
        await msg.answer(
            f"✅ Пресет успешно добавлен на площадку {make_place_pretty_view(preset.get('site'))}"
        )


@router.callback_query(F.data.contains("confirm_referral"))
async def confirm_referral(query: CallbackQuery, state: FSMContext):
    refer_id = query.data.split("|")[-1]

    if str(query.from_user.id) == refer_id:
        await query.message.answer("❌ Вы не можете стать своим рефералом")
        return

    current_user_info = await db.get_user(query.from_user.id)
    if not current_user_info:
        await query.message.answer("❌ Пропишите /start и попробуй заново")
        return

    if current_user_info[0].get("referrer_id"):
        await query.message.answer("❌ Вы уже имеете реферера и не можете его сменить.")
        return

    try:
        refer_user_info = await db.get_user(refer_id)
        if refer_user_info[0].get("referrer_id") == query.from_user.id:
            await query.message.answer(
                "❌ Вы не можете стать рефералом для своего рефера."
            )
            return
    except IndexError:
        await query.message.answer("❌ Что-то пошло не так, попробуйте еще раз")
        return

    try:
        await query.bot.send_message(
            chat_id=CHATS.get("referrals"),
            text=f"Стал рефералом @{query.from_user.username}/{query.from_user.id} - @{await db.get_username_by_id(int(refer_id))}/{refer_id}",
        )
    except Exception:
        logger.error(traceback.format_exc())

    await db.update_user_refer(user_id=query.from_user.id, referrer_id=int(refer_id))
    await query.bot.send_message(
        chat_id=int(refer_id), text=f"У вас новый реферал, @{query.from_user.username}"
    )
    await query.message.answer(
        f"Вы стали рефералом пользователя @{await db.get_username_by_id(int(refer_id))}",
        reply_markup=get_start_menu_markup(query.from_user.id),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@router.callback_query(F.data == "cancel_action")
async def cancel_handler(query: CallbackQuery, state: FSMContext):
    await state.clear()

    with suppress(TelegramAPIError):
        try:
            await query.message.edit_text("Отменено")
        except Exception:
            await query.message.edit_caption(caption="Отменено")

    await query.message.answer(
        "Возвращаю в главное меню...",
        reply_markup=get_start_menu_markup(query.from_user.id),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@dp.message(F.text == "❌ Отмена")
async def cancel_handler(msg, state: FSMContext):
    await state.clear()
    await msg.answer("Выполнено", reply_markup=get_start_menu_markup(msg.from_user.id))


@dp.message(F.text == "❌ Остановить отправку сообщений")
@dp.message(Command("stop_msg"))
async def stop_msg(msg, state: FSMContext):
    await state.clear()

    SENDER_STATUS_DB[str(msg.from_user.id)] = "stop"

    await msg.answer("Выполнено")


@dp.message(F.text == "❌ Остановить отправку сообщений.")
async def stop_msg(msg, state: FSMContext):
    await state.clear()

    SENDER_STATUS_DB[str(msg.from_user.id)] = "stop"

    await msg.answer("Выполнено", reply_markup=get_start_menu_markup(msg.from_user.id))


@router.message(F.text == "❌ Остановить парсинг", IsPrivate(), IsUserHasUsername())
async def stop_parser(msg, state: FSMContext):
    await db.add_parser_status(msg.from_user.id, "stop")

    await msg.answer("Выполнено", reply_markup=get_start_menu_markup(msg.from_user.id))


@router.message(
    F.text == "❌ Быстро остановить парсинг", IsPrivate(), IsUserHasUsername()
)
async def fast_stop_parser(msg, state: FSMContext):
    await db.add_parser_status(msg.from_user.id, "stop_fast")

    await msg.answer("Выполнено", reply_markup=get_start_menu_markup(msg.from_user.id))


@router.callback_query(F.data == "stop_active_parser")
async def stop_active_parser(query: CallbackQuery, state: FSMContext):
    await query.message.answer("✅ Успешно остановлено, попробуйте запустить заново")
    await db.add_parser_status(query.from_user.id, "stop")

    all_stat_ids = await db.get_stats_id_by_user_id(query.from_user.id)
    if all_stat_ids:
        for row in all_stat_ids:
            stat_id = row.get("stat_id")
            await db.remove_stats_ticker(query.from_user.id, stat_id)

    await query.message.answer(
        "Возвращаю в главное меню...",
        reply_markup=get_start_menu_markup(query.from_user.id),
    )

    with suppress(TelegramAPIError):
        await query.answer()


@dp.callback_query(F.data.contains("stop_sender"))
async def stop_sender(query):
    SENDER_STATUS_DB[str(query.from_user.id)] = "stop"
