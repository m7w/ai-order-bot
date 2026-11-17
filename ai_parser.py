import logging
import os

from dotenv import load_dotenv
from openai import APIError, AsyncOpenAI
from pydantic import BaseModel, Field

load_dotenv()
logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)
print(f"DEBUG: Используется base_url = {client.base_url}")
MODEL_NAME = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")


class OrderItem(BaseModel):
    product_name: str = Field(description="Название товара")
    quantity: int = Field(description="Количество единиц товара")


class CustomerOrder(BaseModel):
    items: list[OrderItem] = Field(description="Список заказанных товаров")
    delivery_address: str | None = Field(description="Адрес доставки, если указан")
    customer_phone: str | None = Field(
        description="Контактный телефон клиента, если указан"
    )
    needs_clarification: bool = Field(
        description="True, если не указаны товары, адрес или телефон"
    )
    clarification_question: str | None = Field(
        description="Вежливый вопрос клиенту для уточнения недостающих данных"
    )


SYSTEM_PROMPT = """
Ты — ассистент отдела продаж. Твоя задача — извлечь структурированный заказ из диалога с клиентом.
Для оформления заказа обязательны:
1. Хотя бы один товар с количеством.
2. Адрес доставки.
3. Номер телефона.

Учитывай всю историю переписки. Если клиент ответил на уточняющий вопрос, объедини новые данные с предыдущими.
Если чего-то всё ещё не хватает, поставь needs_clarification = True и задай короткий вежливый вопрос в clarification_question.
"""


async def parse_order_dialog(
    messages_history: list[dict],
) -> CustomerOrder | None:
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages_history

    try:
        completion = await client.chat.completions.parse(
            model=MODEL_NAME,
            messages=full_messages,
            response_format=CustomerOrder,
            temperature=0.1,
        )
        return completion.choices[0].message.parsed
    except APIError:
        logger.exception("Ошибка при обращении к LLM")
        return None
