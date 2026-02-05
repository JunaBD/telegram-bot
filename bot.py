import asyncio
import os
import random

from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor,
    )

def main_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="Получить код")],
        [KeyboardButton(text="Профиль")],
    ]
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
    )
def ensure_user(telegram_user) -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (telegram_id, username, first_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name
                    """,
                    (
                        telegram_user.id,
                        telegram_user.username,
                        telegram_user.first_name,
                    ),
                )
    finally:
        conn.close()


def get_user_stats(telegram_id: int):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE telegram_id = %s",
                    (telegram_id,),
                )
                user_row = cur.fetchone()

                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM codes WHERE user_id = %s",
                    (telegram_id,),
                )
                codes_count_row = cur.fetchone()

                return user_row, codes_count_row["cnt"]
    finally:
        conn.close()


def user_has_code_today(telegram_id: int) -> bool:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM codes
                    WHERE user_id = %s
                      AND created_at::date = CURRENT_DATE
                    """,
                    (telegram_id,),
                )
                row = cur.fetchone()
                return row["cnt"] > 0
    finally:
        conn.close()


def generate_code(length: int = 20) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choices(alphabet, k=length))


def save_code(telegram_id: int, code: str) -> None:
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO codes (user_id, code)
                    VALUES (%s, %s)
                    """,
                    (telegram_id, code),
                )
    finally:
        conn.close()

dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user)

    text = (
        "Привет! Я бот, который выдаёт тебе один случайный код из 20 символов в день.\n\n"
        "Нажми «Получить код», чтобы получить код на сегодня."
    )
    await message.answer(text, reply_markup=main_keyboard())


@dp.message(Command("code"))
@dp.message(F.text == "Получить код")
async def cmd_code(message: Message):
    ensure_user(message.from_user)

    tg_id = message.from_user.id

    if user_has_code_today(tg_id):
        await message.answer("Сегодня ты уже получал код. Новый будет доступен завтра.")
        return

    code = generate_code()
    save_code(tg_id, code)

    await message.answer(f"Твой код на сегодня:\n`{code}`", parse_mode="Markdown")


@dp.message(F.text == "Профиль")
async def cmd_profile(message: Message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id

    user_row, codes_count = get_user_stats(tg_id)

    if not user_row:
        await message.answer("Профиль не найден, попробуй ещё раз /start.")
        return

    text = (
        f"Твой профиль:\n"
        f"ID: {user_row['telegram_id']}\n"
        f"Имя: {user_row.get('first_name')}\n"
        f"Username: @{user_row.get('username')}\n"
        f"Всего кодов получено: {codes_count}"
    )
    await message.answer(text, reply_markup=main_keyboard())

async def main():
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
