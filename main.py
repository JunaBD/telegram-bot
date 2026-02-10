from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

# 1. Загрузка переменных ПЕРВЫМИ
load_dotenv()

# 2. FastAPI ПЕРВЫЙ (до всех импортов!)
app = FastAPI()

# 3. Переменные ПОСЛЕ app
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

print(f"🤖 Starting bot... Token: {'OK' if BOT_TOKEN else 'MISSING'}")
print(f"🌐 Webhook: {WEBHOOK_URL}")

# 4. Ленивые функции (импорты внутри функций)
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
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    return Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

def main_keyboard():
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    kb = [["Получить код"], ["Профиль"]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# База данных (ленивая)
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
                row = cur.fetchone()
                return row[0] > 0
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

# 5. Lifespan (установка webhook)
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting bot...")
    bot = await get_bot()
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook установлен: {WEBHOOK_URL}")
    yield
    print("🛑 Stopping bot...")
    await bot.delete_webhook()

# 6. Переопределяем app с lifespan
app = FastAPI(lifespan=lifespan)

# 7. Роуты
@app.post(WEBHOOK_PATH)
async def webhook(update: dict):
    from aiogram import Dispatcher
    from aiogram.types import Update
    from aiogram.filters import CommandStart, Command
    from aiogram import F
    
    bot = await get_bot()
    dp = Dispatcher()
    
    # Хэндлеры внутри webhook (чтобы избежать проблем с импортами)
    @dp.message(CommandStart())
    async def cmd_start(message):
        ensure_user(message.from_user)
        await message.answer(
            "👋 Привет! Генератор кодов!\n\n"
            "📋 Один код в день\n"
            "👤 Статистика в профиле\n\n"
            "Нажми «Получить код»!",
            reply_markup=main_keyboard()
        )
    
    @dp.message(F.text == "Получить код", Command("code"))
    async def cmd_code(message):
        ensure_user(message.from_user)
        tg_id = message.from_user.id
        
        if user_has_code_today(tg_id):
            await message.answer(
                "⏳ Код на сегодня уже получен!\n🔄 Новый завтра!",
                reply_markup=main_keyboard()
            )
            return
        
        code = generate_code()
        save_code(tg_id, code)
        
        await message.answer(
            f"✅ **Твой код:**\n\n```{code}```\n\n💾 Сохранено!",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    
    @dp.message(F.text == "Профиль")
    async def cmd_profile(message):
        ensure_user(message.from_user)
        tg_id = message.from_user.id
        
        conn = get_db_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM users WHERE telegram_id = %s", (tg_id,))
                    user_row = cur.fetchone()
                    if not user_row:
                        await message.answer("❌ /start сначала!")
                        return
                    
                    cur.execute("SELECT COUNT(*) AS cnt FROM codes WHERE user_id = %s", (tg_id,))
                    codes_count = cur.fetchone()[0]
                    
                    text = (
                        f"👤 **Профиль**\n\n"
                        f"🆔 `{user_row[0]}`\n"
                        f"👤 {user_row[2] or '—'}\n"
                        f"📛 @{user_row[1] or '—'}\n"
                        f"📊 Кодов: **{codes_count}**"
                    )
                    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())
        finally:
            conn.close()
    
    # Обработка update
    update_obj = Update(**update)
    await dp.feed_update(bot, update_obj)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "🤖 Bot работает!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
