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
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties

# Загрузка переменных
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "mysecret123")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

# Глобальные объекты
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# База данных
def get_connection():
    """Подключение к PostgreSQL"""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor,
    )

def main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    kb = [
        [KeyboardButton(text="Получить код")],
        [KeyboardButton(text="Профиль")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def ensure_user(telegram_user):
    """Сохраняет/обновляет пользователя"""
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

def user_has_code_today(telegram_id: int) -> bool:
    """Проверяет код на сегодня"""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM codes
                    WHERE user_id = %s AND created_at::date = CURRENT_DATE
                    """,
                    (telegram_id,),
                )
                row = cur.fetchone()
                return row["cnt"] > 0
    finally:
        conn.close()

def get_user_stats(telegram_id: int):
    """Статистика пользователя"""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                user_row = cur.fetchone()
                
                cur.execute("SELECT COUNT(*) AS cnt FROM codes WHERE user_id = %s", (telegram_id,))
                codes_count_row = cur.fetchone()
                
                return user_row, codes_count_row["cnt"]
    finally:
        conn.close()

def generate_code(length: int = 20) -> str:
    """Генерация кода"""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choices(alphabet, k=length))

def save_code(telegram_id: int, code: str):
    """Сохранение кода"""
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO codes (user_id, code) VALUES (%s, %s)", (telegram_id, code))
    finally:
        conn.close()

# Обработчики сообщений
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

# FastAPI приложение
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения"""
    # Startup
    print("🚀 Starting bot...")
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook установлен: {WEBHOOK_URL}")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down bot...")
    await bot.delete_webhook()
    await bot.session.close()

app = FastAPI(title="Telegram Code Bot", lifespan=lifespan)

@app.get("/")
async def root():
    """Health check"""
    return {"message": "Bot is running!", "webhook": WEBHOOK_URL}

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Webhook обработчик"""
    update = await request.json()
    
    # Передаем update в диспетчер aiogram
    await dp.feed_update(bot, update)
    
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    print(f"🚀 Starting server on port {port}")
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=port, 
        log_level="info",
        reload=False
    )
