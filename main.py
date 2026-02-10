from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, Update
from aiogram.client.default import DefaultBotProperties
import os
import random
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import asynccontextmanager

# Загрузка переменных
load_dotenv()

# Переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

print(f"🤖 Bot token: {'OK' if BOT_TOKEN else 'MISSING'}")
print(f"🗄️ DB host: {'OK' if DB_HOST else 'MISSING'}")
print(f"🌐 Webhook URL: {WEBHOOK_URL}")

# Бот и диспетчер ГЛОБАЛЬНО (до app!)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# База данных
def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor,
    )

def main_keyboard():
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
                    SET username = EXCLUDED.username, 
                        first_name = EXCLUDED.first_name
                    """,
                    (telegram_user.id, telegram_user.username, telegram_user.first_name or ''),
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
                    WHERE user_id = %s AND created_at::date = CURRENT_DATE
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
                cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                user_row = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS cnt FROM codes WHERE user_id = %s", (telegram_id,))
                codes_count = cur.fetchone()["cnt"]
                return user_row, codes_count
    finally:
        conn.close()

def generate_code(length=20) -> str:
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

# ХЭНДЛЕРЫ
@dp.message(CommandStart())
async def cmd_start(message: Message):
    ensure_user(message.from_user)
    await message.answer(
        "👋 Привет! Генератор кодов!\n\n"
        "📋 Один код в день\n"
        "👤 Статистика в профиле\n\n"
        "Нажми «Получить код»!",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "Получить код", Command("code"))
async def cmd_code(message: Message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id

    if user_has_code_today(tg_id):
        await message.answer(
            "⏳ Код на сегодня уже получен!\n"
            "🔄 Новый завтра!",
            reply_markup=main_keyboard()
        )
        return

    code = generate_code()
    save_code(tg_id, code)
    
    await message.answer(
        f"✅ **Твой код:**\n\n"
        f"```{code}```\n\n"
        f"💾 Сохранено в профиле!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "Профиль")
async def cmd_profile(message: Message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id

    user_row, codes_count = get_user_stats(tg_id)
    if not user_row:
        await message.answer("❌ /start сначала!")
        return

    text = (
        f"👤 **Профиль**\n\n"
        f"🆔 `{user_row['telegram_id']}`\n"
        f"👤 {user_row.get('first_name', '—')}\n"
        f"📛 @{user_row.get('username', '—')}\n"
        f"📅 {user_row['created_at'].strftime('%d.%m.%Y')}\n\n"
        f"📊 **Кодов: {codes_count}**"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

# LIFESPAN (ДО app!)
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Запуск бота...")
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook: {WEBHOOK_URL}")
    yield
    print("🛑 Остановка...")
    await bot.delete_webhook()

# ✅ APP ПЕРВЫЙ ВСЁ!
app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def webhook(update: Update):
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "🤖 Bot OK"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
