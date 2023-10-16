from aiogram import types, Router
from aiogram.fsm.context import FSMContext

from app import dp
from app.handlers.filters_validation import (
    check_price_state,
    seller_item_amount_text,
    seller_join_date_text,
    check_seller_item_amount,
    item_insert_date_text,
    check_seller_join_date,
    check_item_insert_date,
    save_preset_text,
)
from app.keyboards.memorable_filters import (
    get_seller_item_amount,
    get_seller_date_button,
    get_ads_date_button,
    choice_btns,
)
from app.states.states import Willhaben

router = Router()
dp.include_router(router)


@router.message(Willhaben.price)
async def state_1(msg: types.Message, state: FSMContext):
    result = await check_price_state(msg, state)
    if not result:
        return

    user_date = await state.get_data()
    site = user_date.get("site")

    await msg.answer(
        seller_item_amount_text,
        reply_markup=await get_seller_item_amount(
            save_type="seller_item_amount", user_id=msg.from_user.id, site=site
        ),
    )
    await state.set_state(Willhaben.seller_item_amount)


@router.message(Willhaben.seller_item_amount)
async def state_2(msg: types.Message, state: FSMContext):
    result = await check_seller_item_amount(msg, state)
    if not result:
        return

    user_date = await state.get_data()
    site = user_date.get("site")

    await msg.answer(
        seller_join_date_text,
        reply_markup=await get_seller_date_button(
            save_type="seller_join_date", user_id=msg.from_user.id, site=site
        ),
    )
    await state.set_state(Willhaben.seller_join_date)


@router.message(Willhaben.seller_join_date)
async def state_3(msg: types.Message, state: FSMContext):
    result = await check_seller_join_date(msg, state)
    if not result:
        return

    user_date = await state.get_data()
    site = user_date.get("site")

    await msg.answer(
        item_insert_date_text,
        reply_markup=await get_ads_date_button(
            save_type="item_insert_date", user_id=msg.from_user.id, site=site
        ),
    )
    await state.set_state(Willhaben.item_insert_date)


@router.message(Willhaben.item_insert_date)
async def state_4(msg: types.Message, state: FSMContext):
    result = await check_item_insert_date(msg, state)
    if not result:
        return

    await msg.answer(save_preset_text, reply_markup=choice_btns)
    await state.set_state("preset_choice")
