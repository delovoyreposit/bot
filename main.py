import asyncio
import sqlite3
import os
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ ---
load_dotenv()

API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = [int(os.getenv('ADMIN_ID', 0))]
KITCHEN_CHAT_ID = int(os.getenv('KITCHEN_ID', 0))
OWNER_ID = int(os.getenv('ADMIN_ID', 0))
WEBAPP_URL = os.getenv('WEBAPP_URL')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# --- ИНИЦИАЛИЗАЦИЯ БОТА И API ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
app = FastAPI()

# Настройка CORS для GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Схема данных для кнопок подтверждения заказа
class OrderConfirm(CallbackData, prefix="order"):
    item: str
    price: float

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, username TEXT, last_order_date DATETIME)''')
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

# --- ОБРАБОТЧИКИ БОТА ---

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="🍕 Открыть Меню", 
        web_app=types.WebAppInfo(url=WEBAPP_URL))
    )
    
    welcome_text = (
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я помогу тебе сделать заказ. Нажми кнопку ниже, выбери блюда, "
        "и я пришлю тебе подтверждение прямо сюда."
    )
    await message.answer(welcome_text, reply_markup=builder.as_markup())

# Команда /admin
@dp.message(Command("admin"), F.from_user.id.in_(ADMIN_IDS))
async def admin_panel(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="👥 Список клиентов", callback_data="view_customers"))
    await message.answer("🛠 Панель администратора:", reply_markup=builder.as_markup())

# Обработка кнопки "Подтвердить" (Имитация оплаты)
@dp.callback_query(OrderConfirm.filter())
async def process_test_confirm(callback: types.CallbackQuery, callback_data: OrderConfirm):
    user_id = callback.from_user.id
    username = callback.from_user.username or "unknown"
    
    # 1. Обновляем активность клиента в БД
    update_user_activity(user_id, username)
    
    # 2. Уведомление на кухню
    await bot.send_message(
        KITCHEN_CHAT_ID, 
        f"👨‍🍳 НОВЫЙ ЗАКАЗ!\nСостав: {callback_data.item}\nСумма: {callback_data.price}₽\nКлиент: @{username}"
    )
    
    # 3. Уведомление владельцу (чеку)
    await bot.send_message(
        OWNER_ID, 
        f"💰 ОПЛАТА (ТЕСТ): {callback_data.price}₽\nЗаказ: {callback_data.item}\nКлиент: @{username}"
    )
    
    # 4. Обновляем сообщение у пользователя
    await callback.message.edit_text(
        f"✅ Заказ «{callback_data.item}» оплачен и передан на кухню!\nОжидайте уведомления о готовности."
    )
    await callback.answer("Заказ принят!")

# Просмотр клиентов (админка)
@dp.callback_query(F.data == "view_customers")
async def list_customers(callback: types.CallbackQuery):
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute("SELECT username, last_order_date FROM users ORDER BY last_order_date DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    
    text = "Последние 10 клиентов:\n\n"
    for r in rows:
        text += f"👤 @{r[0]} — {r[1][:16]}\n"
    
    await callback.message.answer(text)

# --- API ЭНДПОИНТЫ (FASTAPI) ---

@app.post("/api/new_order")
async def receive_order(request: Request):
    try:
        data = await request.json()
        user_id = data['user_id']
        item_name = data['items']
        price = data['total']

        # Вместо выставления счета шлем сообщение с кнопкой подтверждения
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(
            text=f"💳 Оплатить {price}₽", 
            callback_data=OrderConfirm(item=item_name, price=price).pack())
        )

        await bot.send_message(
            user_id,
            f"📦 *Ваш заказ сформирован*\n\nТовар: {item_name}\nИтого к оплате: *{price}₽*\n\nНажмите кнопку ниже для подтверждения.",
            parse_mode="Markdown",
            reply_markup=builder.as_markup()
        )
        return {"status": "success", "message": "Confirmation sent"}
    except Exception as e:
        logging.error(f"Error in API: {e}")
        return {"status": "error", "message": str(e)}

# --- ФОНОВЫЕ ЗАДАЧИ ---

async def reminder_loop():
    """Рассылка напоминаний тем, кто не заказывал более 2 дней"""
    while True:
        try:
            conn = sqlite3.connect('orders.db')
            cur = conn.cursor()
            two_days_ago = datetime.now() - timedelta(days=2)
            cur.execute("SELECT id FROM users WHERE last_order_date < ?", (two_days_ago,))
            users_to_remind = cur.fetchall()
            conn.close()

            for user in users_to_remind:
                try:
                    await bot.send_message(user[0], "👋 Мы соскучились! Не хотите заказать что-нибудь вкусненькое сегодня?")
                except Exception:
                    pass # Пользователь мог заблокировать бота
        except Exception as e:
            logging.error(f"Error in reminder loop: {e}")
        
        await asyncio.sleep(86400) # Проверка раз в сутки

# --- ЗАПУСК ---

async def main():
    init_db()
    # Запускаем фоновую задачу напоминаний
    asyncio.create_task(reminder_loop())
    
    # Настройка сервера Uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    
    # Запуск бота и API
    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")