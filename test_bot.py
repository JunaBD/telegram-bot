import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
print(f"🤖 Bot token: {BOT_TOKEN[:20]}...")  # первые 20 символов

try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    print("✅ БД подключена!")
    conn.close()
except Exception as e:
    print(f"❌ Ошибка БД: {e}")
