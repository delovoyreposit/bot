import logging
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.filters import Text

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = '8639880686:AAEtEIHgNWhNDGOfLzANDeox07uklEAFfRI'  # Токен от @BotFather
ADMIN_ID = 8243458209

# Список доступных часов (кнопки)
WORKING_HOURS = ["09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00", "17:00"]

logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Состояния
class Appointment(StatesGroup):
    waiting_for_name = State()
    waiting_for_time = State()

# Клавиатура с временем
def get_time_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    buttons = [
        types.InlineKeyboardButton(text=hour, callback_data=f"time_{hour}") 
        for hour in WORKING_HOURS
    ]
    keyboard.add(*buttons)
    return keyboard

# Команда /start
@dp.message_handler(commands=['start'], state="*")
async def cmd_start(message: types.Message):
    await message.answer("Здравствуйте! Введите ваше имя для записи на прием:")
    await Appointment.waiting_for_name.set()

# Получаем имя
@dp.message_handler(state=Appointment.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer(
        f"Приятно познакомиться, {message.text}! Выберите удобное время:",
        reply_markup=get_time_keyboard()
    )
    await Appointment.waiting_for_time.set()

# Получаем время (через кнопку)
@dp.callback_query_handler(Text(startswith="time_"), state=Appointment.waiting_for_time)
async def process_time_callback(callback: types.CallbackQuery, state: FSMContext):
    selected_time = callback.data.split("_")[1]
    user_data = await state.get_data()
    name = user_data.get('name')
    
    # Ссылка на профиль пользователя
    username = f"@{callback.from_user.username}" if callback.from_user.username else "Скрыт"
    user_id = callback.from_user.id

    # 1. Ответ пользователю
    await callback.message.edit_text(f"Спасибо, {name}! Ваша заявка отправлена. Мы свяжемся с вами для подтверждения.")
    
    # 2. Уведомление администратору (вам)
    admin_text = (
        f"🔔 **Новая запись на прием!**\n\n"
        f"👤 **Имя:** {name}\n"
        f"⏰ **Время:** {selected_time}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"📱 **TG:** {username}"
    )
    
    await bot.send_message(ADMIN_ID, admin_text, parse_mode="Markdown")
    
    # Завершаем работу FSM
    await state.finish()

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)