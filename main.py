import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv # pip install python-dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Загрузка переменных из .env
load_dotenv()

API_TOKEN = os.getenv('BOT_TOKEN')
PAYMENT_TOKEN = os.getenv('PAYMENT_TOKEN')
ADMIN_IDS = [int(os.getenv('ADMIN_ID'))]
KITCHEN_CHAT_ID = int(os.getenv('KITCHEN_ID'))
WEBAPP_URL = os.getenv('WEBAPP_URL')

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
app = FastAPI()

# Разрешаем запросы от вашего GitHub Pages (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def init_db():
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, username TEXT, last_order_date DATETIME)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS products 
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL)''')
    
    # Добавим тестовые товары, если таблица пуста
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        menu_items = [('Пицца Маргарита', 550.0), ('Пицца Пепперони', 650.0), ('Кола 0.5', 120.0)]
        cur.executemany("INSERT INTO products (name, price) VALUES (?, ?)", menu_items)
    
    conn.commit()
    conn.close()

# --- ПРИВЕТСТВИЕ И КНОПКА МИНЯ-АПП ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    # Кнопка, которая открывает Web App
    builder.row(types.InlineKeyboardButton(
        text="🍕 Сделать заказ (Меню)", 
        web_app=types.WebAppInfo(url=WEBAPP_URL))
    )
    
    welcome_text = (
        f"Привет, {message.from_user.full_name}! 👋\n\n"
        "Добро пожаловать в наш сервис заказа еды.\n"
        "Нажми на кнопку ниже, чтобы выбрать блюда и оформить заказ прямо здесь!"
    )
    
    await message.answer(welcome_text, reply_markup=builder.as_markup())

# --- ОБРАБОТКА ОПЛАТЫ ---
@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def on_success(message: types.Message):
    # Обновляем активность
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", 
               (message.from_user.id, message.from_user.username, datetime.now()))
    conn.commit()
    conn.close()

    await bot.send_message(KITCHEN_CHAT_ID, f"✅ ОПЛАЧЕНО: {message.successful_payment.invoice_payload}")
    await message.answer("Заказ принят! Мы уже начали готовить.")

# --- API ДЛЯ ЗАКАЗА ---
@app.post("/api/new_order")
async def create_invoice(request: Request):
    data = await request.json()
    await bot.send_invoice(
        data['user_id'],
        title="Ваш заказ",
        description=data['items'],
        payload=data['items'],
        provider_token=PAYMENT_TOKEN,
        currency="RUB",
        prices=[types.LabeledPrice(label="Итого", amount=int(data['total'] * 100))]
    )
    return {"ok": True}

async def main():
    init_db()
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    await asyncio.gather(dp.start_polling(bot), server.serve())

if __name__ == "__main__":
    asyncio.run(main())