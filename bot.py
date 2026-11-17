import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv

from ai_parser import parse_order_dialog
from database import init_db, save_order  # Импортируем функции БД

load_dotenv()
logging.basicConfig(level=logging.INFO)

token = os.getenv("BOT_TOKEN")
if not token:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")
bot = Bot(token)
dp = Dispatcher(storage=MemoryStorage())

MAX_ATTEMPTS = 6


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

    status_msg = await message.answer("⏳ Обрабатываю заявку...")
    history.append({"role": "user", "content": message.text})

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

    # Очищаем историю диалога
    await state.clear()

    # Сохраняем готовый заказ в SQLite и получаем его реальный номер
    if message.from_user is None:
        return

    order_id = await save_order(
        user_id=message.from_user.id, order_data=result.model_dump()
    )

    items_text = "\n".join(
        [f"• {item.product_name} — {item.quantity} шт." for item in result.items]
    )

    response_text = (
        f"✅ **Заказ №{order_id} сформирован!**\n\n"
        f"**Товары:**\n{items_text}\n\n"
        f"**Адрес:** {result.delivery_address}\n"
        f"**Телефон:** {result.customer_phone}\n\n"
        "📦 *Заявка поставлена в очередь на передачу в учетную систему (1С).*"
    )
    await status_msg.edit_text(response_text, parse_mode="Markdown")


async def main():
    await init_db()  # Создаем таблицу orders перед запуском polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
