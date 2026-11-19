import asyncio
import logging
import os
import socket

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from ai_parser import parse_order_dialog
from database import init_db, save_order  # Импортируем функции БД

load_dotenv()
logging.basicConfig(level=logging.INFO)

session = AiohttpSession()
session._connector_init = {"family": socket.AF_INET}

token = os.getenv("BOT_TOKEN")
if not token:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")
bot = Bot(token)
dp = Dispatcher(storage=MemoryStorage())

MAX_ATTEMPTS = 6
MAX_INPUT_CHARS = 500


class OrderState(StatesGroup):
    waiting_for_confirmation = State()
    waiting_for_edit = State()


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте! Напишите ваш заказ в свободной форме.\n"
        "Укажите товары, количество, адрес доставки и ваш телефон.\n\n"
        "Для сброса диалога нажмите /cancel"
    )


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Текущий заказ сброшен. Можете начать новый!")


@dp.message(F.text)
async def handle_order(message: Message, state: FSMContext):
    current_state = await state.get_state()
    data = await state.get_data()
    history = data.get("history", [])
    attempts = data.get("attempts", 0) + 1

    if attempts > MAX_ATTEMPTS:
        await state.clear()
        await message.answer(
            "👩‍💼 Похоже, возникли сложности с автоматическим оформлением. "
            "Я передал ваш диалог живому менеджеру — он скоро свяжется с вами!\n\n"
            "Чтобы попробовать снова с нуля, нажмите /start."
        )
        return

    # Если пользователь находился в состоянии подтверждения или редактирования и прислал текст
    if current_state in (
        OrderState.waiting_for_confirmation.state,
        OrderState.waiting_for_edit.state,
    ):
        await state.set_state(None)

    status_msg = await message.answer("⏳ Обрабатываю заявку...")

    content = message.text[:MAX_INPUT_CHARS] if message.text else None
    history.append({"role": "user", "content": content})

    result = await parse_order_dialog(history)

    if result is None:
        await status_msg.edit_text(
            "⚠️ Не удалось автоматически распознать заявку. Попробуйте еще раз или позовите менеджера."
        )
        return

    if isinstance(result, str):
        history.append({"role": "assistant", "content": result})
        await state.update_data(history=history, attempts=attempts)
        await status_msg.edit_text(f"❓ {result} (попытка {attempts}/{MAX_ATTEMPTS})")
        return

    if result.needs_clarification and result.clarification_question:
        history.append({"role": "assistant", "content": result.clarification_question})
        await state.update_data(history=history, attempts=attempts)
        await status_msg.edit_text(
            f"❓ {result.clarification_question} (попытка {attempts}/{MAX_ATTEMPTS})"
        )
        return

    # Заказ собран, просим подтверждение у пользователя
    order_data = result.model_dump()
    await state.update_data(order_data=order_data, history=history, attempts=attempts)
    await state.set_state(OrderState.waiting_for_confirmation)

    items_text = "\n".join(
        [f"• {item.product_name} — {item.quantity} шт." for item in result.items]
    )

    summary_text = (
        f"📋 **Проверьте данные вашего заказа:**\n\n"
        f"**Товары:**\n{items_text}\n\n"
        f"**Адрес:** {result.delivery_address}\n"
        f"**Телефон:** {result.customer_phone}\n\n"
        "Всё указано верно?"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Все верно, оформить", callback_data="confirm_order"
                ),
                InlineKeyboardButton(
                    text="Изменить данные", callback_data="edit_order"
                ),
            ]
        ]
    )

    await status_msg.edit_text(
        summary_text, parse_mode="Markdown", reply_markup=keyboard
    )


@dp.callback_query(F.data == "confirm_order", OrderState.waiting_for_confirmation)
async def process_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_data = data.get("order_data")
    if not order_data:
        await callback.answer(
            "Данные заказа не найдены. Начните сначала /start", show_alert=True
        )
        await state.clear()
        return

    if callback.from_user is None:
        return

    order_id = await save_order(user_id=callback.from_user.id, order_data=order_data)

    items_text = "\n".join(
        [
            f"• {item['product_name']} — {item['quantity']} шт."
            for item in order_data["items"]
        ]
    )

    response_text = (
        f"✅ **Заказ №{order_id} сформирован!**\n\n"
        f"**Товары:**\n{items_text}\n\n"
        f"**Адрес:** {order_data['delivery_address']}\n"
        f"**Телефон:** {order_data['customer_phone']}\n\n"
        "📦 *Заявка поставлена в очередь на передачу в учетную систему (1С).*"
    )
    await callback.message.edit_text(response_text, parse_mode="Markdown")
    await state.clear()
    await callback.answer()


@dp.callback_query(F.data == "edit_order", OrderState.waiting_for_confirmation)
async def process_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_for_edit)
    await callback.message.edit_text(
        "Напишите, что именно нужно изменить (например: адрес, телефон или количество товаров)."
    )
    await callback.answer()


async def main():
    await init_db()  # Создаем таблицу orders перед запуском polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
