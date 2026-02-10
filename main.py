from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Update
from aiogram.filters import CommandStart, Command

load_dotenv()

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

# Глобальный диспетчер
dp = Dispatcher()

print(f"🤖 Bot starting... Webhook: {WEBHOOK_URL}")

def get_db_connection():
    from psycopg import connect
    return connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

async def get_bot():
    return Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

def main_keyboard():
    kb = [
        [KeyboardButton(text="Получить код")],
        [KeyboardButton(text="Профиль")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def ensure_user(telegram_user):
    conn = get_db_connection()
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
                    (telegram_user.id, telegram_user.username or '', telegram_user.first_name or ''),
                )
    finally:
        conn.close()

def user_has_code_today(telegram_id: int) -> bool:
    conn = get_db_connection()
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
                return cur.fetchone()[0] > 0
    finally:
        conn.close()

def generate_code(length=20) -> str:
    import random
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(random.choices(alphabet, k=length))

def save_code(telegram_id: int, code: str):
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO codes (user_id, code) VALUES (%s, %s)",
                    (telegram_id, code),
                )
    finally:
        conn.close()

def get_user_stats(telegram_id: int):
    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                user_row = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS cnt FROM codes WHERE user_id = %s", (telegram_id,))
                codes_count = cur.fetchone()[0]
                return user_row, codes_count
    finally:
        conn.close()

# Регистрация обработчиков
@dp.message(CommandStart())
async def cmd_start(message):
    ensure_user(message.from_user)
    await message.answer(
        "👋 Генератор кодов!\n\n📋 Один код в день\n👤 Профиль\n\nНажми «Получить код»!",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "Получить код")
async def cmd_code(message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id
    
    if user_has_code_today(tg_id):
        await message.answer(
            "⏳ Код на сегодня получен!\n🔄 Новый завтра!",
            reply_markup=main_keyboard()
        )
        return
    
    code = generate_code()
    save_code(tg_id, code)
    
    await message.answer(
        f"✅ **Код:**\n\n```\n{code}\n```\n\n💾 Сохранено!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "Профиль")
async def cmd_profile(message):
    ensure_user(message.from_user)
    tg_id = message.from_user.id
    
    user_row, codes_count = get_user_stats(tg_id)
    if not user_row:
        await message.answer("❌ /start сначала!")
        return
    
    text = (
        f"👤 **Профиль**\n\n"
        f"🆔 `{user_row[0]}`\n"
        f"👤 {user_row[2] or '—'}\n"
        f"📛 @{user_row[1] or '—'}\n"
        f"📊 **Кодов: {codes_count}**"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting...")
    bot = await get_bot()
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook OK: {WEBHOOK_URL}")
    yield
    print("🛑 Stopping...")
    await bot.delete_webhook()

app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def webhook(update: dict):
    bot = await get_bot()
    update_obj = Update(**update)
    await dp.feed_update(bot, update_obj)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "🤖 Bot работает!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
