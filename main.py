import asyncio
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from fastapi import FastAPI, Request
import uvicorn
from aiogram import F
from aiogram.types import Message

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = '8769758762:AAH12Pbcym3iggFnwEYJLHrLScgc8uk4gxg'
PAYMENT_TOKEN = 'ВАШ_ПЛАТЕЖНЫЙ_ТОКЕН' # От @BotFather
ADMIN_IDS = [ 8243458209] # Замените на ваш ID
KITCHEN_CHAT_ID = -100123456789 # ID группы кухни
OWNER_ID =  8243458209 # Можно дублировать ваш ID

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    # Пользователи
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, username TEXT, last_order_date DATETIME)''')
    # Меню
    cur.execute('''CREATE TABLE IF NOT EXISTS products 
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price REAL)''')
    # Заказы
    cur.execute('''CREATE TABLE IF NOT EXISTS orders 
                   (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, items TEXT, status TEXT)''')
    conn.commit()
    conn.close()

def update_user_activity(user_id, username):
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users (id, username, last_order_date) VALUES (?, ?, ?)",
                (user_id, username, datetime.now()))
    conn.commit()
    conn.close()

# --- БОТ (AIOGRAM) ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="Открыть меню 🍕", 
        web_app=types.WebAppInfo(url="https://your-app-url.com"))
    )
    await message.answer("Добро пожаловать! Нажмите кнопку ниже, чтобы сделать заказ:", reply_markup=builder.as_markup())

@dp.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📊 Заказы (Web App)", web_app=types.WebAppInfo(url="https://your-app-url.com/admin")))
    builder.row(types.InlineKeyboardButton(text="👥 Клиенты", callback_data="view_customers"))
    await message.answer("🛠 Панель управления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "view_customers")
async def list_customers(callback: types.CallbackQuery):
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute("SELECT username, last_order_date FROM users LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    text = "Последние клиенты:\n" + "\n".join([f"@{r[0]} - {r[1]}" for r in rows])
    await callback.message.answer(text)

# Платежи
@dp.pre_checkout_query()
async def process_pre_checkout(query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

# Вместо @dp.successful_payment() используйте это:
@dp.message(F.successful_payment)
async def on_success_pay(message: Message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload
    
    # Сохраняем/обновляем активность пользователя
    update_user_activity(user_id, message.from_user.username)
    
    # 1. Отправка на кухню
    await bot.send_message(
        KITCHEN_CHAT_ID, 
        f"👨‍🍳 ЗАКАЗ ОПЛАЧЕН!\nСостав: {payload}\nКлиент: @{message.from_user.username}"
    )
    
    # 2. Отправка чека владельцу
    await bot.send_message(
        OWNER_ID, 
        f"💰 Чек: {message.successful_payment.total_amount/100} {message.successful_payment.currency}\nОт: @{message.from_user.username}"
    )
    
    # 3. Подтверждение клиенту
    await message.answer("Спасибо за оплату! Ваш заказ передан на кухню.")
# --- API (FASTAPI) ---
app = FastAPI()

@app.post("/api/new_order")
async def new_order(request: Request):
    data = await request.json()
    # Отправляем инвойс пользователю
    await bot.send_invoice(
        data['user_id'],
        title="Ваш заказ",
        description=data['items_summary'],
        payload=data['items_summary'],
        provider_token=PAYMENT_TOKEN,
        currency="RUB",
        prices=[types.LabeledPrice(label="Заказ", amount=int(data['total'] * 100))]
    )
    return {"status": "invoice_sent"}

@app.post("/api/order_ready/{order_id}")
async def set_ready(order_id: int, user_id: int):
    await bot.send_message(user_id, "✅ Ваш заказ готов! Ждем вас.")
    return {"status": "notified"}

# --- ФОНОВЫЕ ЗАДАЧИ ---
async def reminder_loop():
    while True:
        conn = sqlite3.connect('orders.db')
        cur = conn.cursor()
        two_days_ago = datetime.now() - timedelta(days=2)
        cur.execute("SELECT id FROM users WHERE last_order_date < ?", (two_days_ago,))
        for row in cur.fetchall():
            try:
                await bot.send_message(row[0], "👋 Давно не виделись! Не хотите заказать что-нибудь сегодня?")
            except: pass
        conn.close()
        await asyncio.sleep(86400) # Раз в сутки

# --- ЗАПУСК ---
async def main():
    init_db()
    # Запуск фонового процесса напоминаний
    asyncio.create_task(reminder_loop())
    
    # Запуск бота и API одновременно
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":
    asyncio.run(main())