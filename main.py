import asyncio
import os
import random
from datetime import datetime
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, Update
from aiogram.client.default import DefaultBotProperties

# Загрузка переменных
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

print(f"🤖 Starting bot with webhook: {WEBHOOK_URL}")

# Глобальные объекты
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# База данных
def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
        cursor_factory=RealDictCursor,
    )

def main_keyboard() -> ReplyKeyboardMarkup:
    kb = [["Получить код"], ["Профиль"]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def ensure_user(telegram_user):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (telegram_id, username, first_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE
                    SET username = EXCLUDED.username, first_name = EXCLUDED.first_name
                    """,
                    (telegram_user.id, telegram_user.username, telegram_user.first_name),
                )
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

def generate_code(length: int = 20) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choices(alphabet, k=length))

def save_code(telegram_id: int, code: str):
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO codes (user_id, code) VALUES (%s, %s)",
                    (telegram_id, code),
                )
    finally:
        conn.close()

# Хэндлеры
@dp.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user)
    text = (
        "👋 Привет! Я бот для генерации кодов.\n\n"
        "📋 Функции:\n"
        "• Один уникальный код в день\n"
        "• Статистика в профиле\n\n"
        "Нажми «Получить код» для начала!"
    )
    await message.answer(text, reply_markup=main_keyboard())

@dp.message(Command("code"))
@dp.message(F.text == "Получить код")
async def cmd_code(message: Message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id

    if user_has_code_today(tg_id):
        await message.answer(
            "⏳ Сегодня ты уже получал код.\n"
            "Новый код будет доступен завтра!",
            reply_markup=main_keyboard()
        )
        return

    code = generate_code()
    save_code(tg_id, code)

    await message.answer(
        f"✅ Твой код на сегодня:\n\n"
        f"`{code}`\n\n"
        f"💾 Код сохранён в твоём профиле!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "Профиль")
async def cmd_profile(message: Message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id

    user_row, codes_count = get_user_stats(tg_id)

    if not user_row:
        await message.answer("❌ Профиль не найден. Напиши /start")
        return

    text = (
        f"👤 **Твой профиль**\n\n"
        f"🆔 ID: `{user_row['telegram_id']}`\n"
        f"👤 Имя: {user_row.get('first_name', 'Не указано')}\n"
        f"📛 Username: @{user_row.get('username', 'Не указан')}\n"
        f"📅 Зарегистрирован: {user_row['created_at'].strftime('%d.%m.%Y')}\n\n"
        f"📊 **Статистика**\n"
        f"Всего кодов: **{codes_count}**"
    )
    
    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

# FastAPI - ВСЁ В КОНЦЕ!
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting bot...")
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook set: {WEBHOOK_URL}")
    yield
    print("🛑 Shutting down bot...")
    await bot.delete_webhook()

# ✅ app = ПЕРВЫЙ создаём, потом декораторы!
app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def webhook(update: Update, _: Request):
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "🤖 Bot is running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
