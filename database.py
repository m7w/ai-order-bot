import json
from datetime import datetime

import aiosqlite

DB_NAME = "orders.db"


async def init_db():
    """Создает таблицу заказов при старте бота, если её еще нет."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                delivery_address TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                sync_status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()


async def save_order(user_id: int, order_data: dict) -> int:
    """Сохраняет валидный заказ в SQLite и возвращает его ID."""
    items_json = json.dumps(order_data["items"], ensure_ascii=False)
    created_at = datetime.now().isoformat(timespec="seconds")

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            INSERT INTO orders (
                telegram_user_id, items_json, delivery_address, customer_phone, sync_status, created_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                user_id,
                items_json,
                order_data["delivery_address"],
                order_data["customer_phone"],
                created_at,
            ),
        )
        await db.commit()
        if cursor.lastrowid is None:
            raise ValueError("Не удалось получить ID созданного заказа")
        return cursor.lastrowid
