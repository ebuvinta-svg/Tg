#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Телеграм бот для управления чатами и рассылки сообщений
Поддерживает подключение нескольких чатов к одному пользователю
"""

import telebot
import sqlite3
import json
import logging
import os
from typing import List, Dict, Optional
from telebot import types

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Токен бота (должен быть установлен через переменную окружения)
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("Необходимо установить переменную окружения BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)

# База данных
DB_NAME = 'telegram_bot.db'

class DatabaseManager:
    """Класс для работы с базой данных"""
    
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица чатов пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    chat_title TEXT,
                    chat_type TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица истории сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_text TEXT,
                    sent_to_chats TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            conn.commit()
    
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None):
        """Добавление пользователя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            conn.commit()
    
    def add_chat(self, user_id: int, chat_id: int, chat_title: str, chat_type: str):
        """Добавление чата к пользователю"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # Проверяем, нет ли уже такого чата
            cursor.execute('SELECT id FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
            if cursor.fetchone():
                return False, "Чат уже добавлен"
            
            cursor.execute('''
                INSERT INTO user_chats (user_id, chat_id, chat_title, chat_type)
                VALUES (?, ?, ?, ?)
            ''', (user_id, chat_id, chat_title, chat_type))
            conn.commit()
            return True, "Чат успешно добавлен"
    
    def remove_chat(self, user_id: int, chat_id: int):
        """Удаление чата пользователя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
    
    def get_user_chats(self, user_id: int) -> List[Dict]:
        """Получение всех чатов пользователя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT chat_id, chat_title, chat_type, added_at, is_active
                FROM user_chats 
                WHERE user_id = ? AND is_active = 1
                ORDER BY added_at DESC
            ''', (user_id,))
            
            columns = ['chat_id', 'chat_title', 'chat_type', 'added_at', 'is_active']
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def save_message_history(self, user_id: int, message_text: str, sent_to_chats: List[int], 
                           success_count: int, failed_count: int):
        """Сохранение истории отправленных сообщений"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO message_history (user_id, message_text, sent_to_chats, success_count, failed_count)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, message_text, json.dumps(sent_to_chats), success_count, failed_count))
            conn.commit()

# Инициализация базы данных
db = DatabaseManager(DB_NAME)

# Состояния пользователей
user_states = {}

class UserStates:
    """Константы состояний пользователей"""
    WAITING_FOR_MESSAGE = "waiting_for_message"
    WAITING_FOR_CHAT_ID = "waiting_for_chat_id"
    NORMAL = "normal"

def create_main_keyboard():
    """Создание основной клавиатуры"""
    keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add(
        types.KeyboardButton("📝 Отправить сообщение"),
        types.KeyboardButton("📋 Мои чаты")
    )
    keyboard.add(
        types.KeyboardButton("➕ Добавить чат"),
        types.KeyboardButton("❌ Удалить чат")
    )
    keyboard.add(
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("ℹ️ Помощь")
    )
    return keyboard

def create_cancel_keyboard():
    """Создание клавиатуры отмены"""
    keyboard = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    return keyboard

@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = f"""
👋 Добро пожаловать, {user.first_name}!

Этот бот поможет вам управлять несколькими чатами и отправлять сообщения сразу во все подключенные чаты.

🔧 Основные функции:
• Подключение нескольких чатов
• Массовая рассылка сообщений
• Управление списком чатов
• Просмотр статистики

Для начала работы добавьте чаты с помощью кнопки "➕ Добавить чат"
"""
    
    bot.send_message(message.chat.id, welcome_text, reply_markup=create_main_keyboard())

@bot.message_handler(commands=['help'])
def help_command(message):
    """Обработчик команды /help"""
    help_text = """
🆘 Помощь по использованию бота:

📝 Отправить сообщение - отправляет ваше сообщение во все подключенные чаты
📋 Мои чаты - показывает список ваших чатов
➕ Добавить чат - добавляет новый чат для рассылки
❌ Удалить чат - удаляет чат из списка рассылки
📊 Статистика - показывает статистику использования
ℹ️ Помощь - показывает это сообщение

💡 Как добавить чат:
1. Нажмите "➕ Добавить чат"
2. Добавьте бота в нужный чат как администратора
3. Отправьте ID чата (можно получить через @userinfobot)

⚠️ Важно: бот должен быть администратором в чатах для отправки сообщений!
"""
    
    bot.send_message(message.chat.id, help_text, reply_markup=create_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📋 Мои чаты")
def show_user_chats(message):
    """Показать чаты пользователя"""
    user_chats = db.get_user_chats(message.from_user.id)
    
    if not user_chats:
        bot.send_message(
            message.chat.id, 
            "У вас пока нет подключенных чатов.\nИспользуйте кнопку '➕ Добавить чат' для добавления.",
            reply_markup=create_main_keyboard()
        )
        return
    
    chat_list = "📋 Ваши чаты:\n\n"
    for i, chat in enumerate(user_chats, 1):
        chat_list += f"{i}. {chat['chat_title']} (ID: {chat['chat_id']})\n"
        chat_list += f"   Тип: {chat['chat_type']}\n"
        chat_list += f"   Добавлен: {chat['added_at'][:16]}\n\n"
    
    bot.send_message(message.chat.id, chat_list, reply_markup=create_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "➕ Добавить чат")
def add_chat_request(message):
    """Запрос на добавление чата"""
    user_states[message.from_user.id] = UserStates.WAITING_FOR_CHAT_ID
    
    instruction_text = """
➕ Добавление нового чата

Для добавления чата выполните следующие шаги:

1. Добавьте этого бота в нужный чат
2. Сделайте бота администратором чата
3. Получите ID чата (можно через @userinfobot)
4. Отправьте ID чата в ответ на это сообщение

Формат ID чата: число (например: -1001234567890 для супергруппы или -123456789 для группы)

Отправьте ID чата:
"""
    
    bot.send_message(message.chat.id, instruction_text, reply_markup=create_cancel_keyboard())

@bot.message_handler(func=lambda message: message.text == "❌ Удалить чат")
def remove_chat_request(message):
    """Запрос на удаление чата"""
    user_chats = db.get_user_chats(message.from_user.id)
    
    if not user_chats:
        bot.send_message(
            message.chat.id,
            "У вас нет чатов для удаления.",
            reply_markup=create_main_keyboard()
        )
        return
    
    # Создаем inline клавиатуру с чатами
    keyboard = types.InlineKeyboardMarkup()
    for chat in user_chats:
        callback_data = f"remove_chat_{chat['chat_id']}"
        keyboard.add(types.InlineKeyboardButton(
            f"❌ {chat['chat_title']}", 
            callback_data=callback_data
        ))
    
    bot.send_message(
        message.chat.id,
        "Выберите чат для удаления:",
        reply_markup=keyboard
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('remove_chat_'))
def remove_chat_callback(call):
    """Обработчик удаления чата"""
    chat_id = int(call.data.split('_')[2])
    user_id = call.from_user.id
    
    success = db.remove_chat(user_id, chat_id)
    
    if success:
        bot.answer_callback_query(call.id, "Чат удален!")
        bot.edit_message_text(
            "✅ Чат успешно удален из списка рассылки.",
            call.message.chat.id,
            call.message.message_id
        )
    else:
        bot.answer_callback_query(call.id, "Ошибка при удалении чата")

@bot.message_handler(func=lambda message: message.text == "📝 Отправить сообщение")
def send_message_request(message):
    """Запрос на отправку сообщения"""
    user_chats = db.get_user_chats(message.from_user.id)
    
    if not user_chats:
        bot.send_message(
            message.chat.id,
            "У вас нет подключенных чатов для рассылки.\nСначала добавьте чаты с помощью кнопки '➕ Добавить чат'.",
            reply_markup=create_main_keyboard()
        )
        return
    
    user_states[message.from_user.id] = UserStates.WAITING_FOR_MESSAGE
    
    chat_list = "📝 Сообщение будет отправлено в следующие чаты:\n\n"
    for i, chat in enumerate(user_chats, 1):
        chat_list += f"{i}. {chat['chat_title']}\n"
    
    chat_list += "\nНапишите сообщение для отправки:"
    
    bot.send_message(message.chat.id, chat_list, reply_markup=create_cancel_keyboard())

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    """Показать статистику пользователя"""
    user_chats = db.get_user_chats(message.from_user.id)
    
    stats_text = f"""
📊 Ваша статистика:

👥 Подключенных чатов: {len(user_chats)}
📝 История сообщений: доступна в базе данных
🤖 Бот работает стабильно

💡 Совет: регулярно проверяйте список чатов и удаляйте неактуальные.
"""
    
    bot.send_message(message.chat.id, stats_text, reply_markup=create_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "❌ Отмена")
def cancel_operation(message):
    """Отмена текущей операции"""
    user_states.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        "❌ Операция отменена.",
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "ℹ️ Помощь")
def help_button(message):
    """Обработчик кнопки помощи"""
    help_command(message)

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработчик всех остальных сообщений"""
    user_id = message.from_user.id
    user_state = user_states.get(user_id, UserStates.NORMAL)
    
    if user_state == UserStates.WAITING_FOR_CHAT_ID:
        # Обработка добавления чата
        try:
            chat_id = int(message.text.strip())
            
            # Пробуем получить информацию о чате
            try:
                chat_info = bot.get_chat(chat_id)
                success, result_message = db.add_chat(
                    user_id, 
                    chat_id, 
                    chat_info.title or f"Чат {chat_id}", 
                    chat_info.type
                )
                
                if success:
                    bot.send_message(
                        message.chat.id,
                        f"✅ {result_message}\n\nЧат: {chat_info.title}\nТип: {chat_info.type}",
                        reply_markup=create_main_keyboard()
                    )
                else:
                    bot.send_message(
                        message.chat.id,
                        f"❌ {result_message}",
                        reply_markup=create_main_keyboard()
                    )
                
            except Exception as e:
                bot.send_message(
                    message.chat.id,
                    f"❌ Не удалось получить информацию о чате.\nВозможные причины:\n• Бот не добавлен в чат\n• Неверный ID чата\n• Бот не является администратором\n\nОшибка: {str(e)}",
                    reply_markup=create_main_keyboard()
                )
                
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ Неверный формат ID чата. Введите числовой ID (например: -1001234567890)",
                reply_markup=create_cancel_keyboard()
            )
            return
        
        user_states.pop(user_id, None)
        
    elif user_state == UserStates.WAITING_FOR_MESSAGE:
        # Обработка отправки сообщения
        user_chats = db.get_user_chats(user_id)
        
        if not user_chats:
            bot.send_message(
                message.chat.id,
                "❌ У вас нет подключенных чатов.",
                reply_markup=create_main_keyboard()
            )
            user_states.pop(user_id, None)
            return
        
        # Отправляем сообщение во все чаты
        success_count = 0
        failed_count = 0
        failed_chats = []
        
        status_message = bot.send_message(
            message.chat.id,
            "📤 Отправляю сообщения..."
        )
        
        for chat in user_chats:
            try:
                bot.send_message(chat['chat_id'], message.text)
                success_count += 1
            except Exception as e:
                failed_count += 1
                failed_chats.append(f"{chat['chat_title']}: {str(e)}")
                logger.error(f"Failed to send message to {chat['chat_id']}: {str(e)}")
        
        # Сохраняем историю
        chat_ids = [chat['chat_id'] for chat in user_chats]
        db.save_message_history(user_id, message.text, chat_ids, success_count, failed_count)
        
        # Отправляем отчет
        report = f"📊 Отчет о рассылке:\n\n"
        report += f"✅ Успешно отправлено: {success_count}\n"
        report += f"❌ Не удалось отправить: {failed_count}\n"
        
        if failed_chats:
            report += f"\n🚫 Ошибки:\n"
            for error in failed_chats[:5]:  # Показываем только первые 5 ошибок
                report += f"• {error}\n"
            if len(failed_chats) > 5:
                report += f"... и еще {len(failed_chats) - 5} ошибок"
        
        bot.edit_message_text(
            report,
            message.chat.id,
            status_message.message_id
        )
        
        user_states.pop(user_id, None)
        
        # Возвращаем главную клавиатуру
        bot.send_message(
            message.chat.id,
            "Готово! Что делаем дальше?",
            reply_markup=create_main_keyboard()
        )
        
    else:
        # Обычное состояние - показываем помощь
        bot.send_message(
            message.chat.id,
            "Используйте кнопки меню для взаимодействия с ботом.\nДля получения помощи нажмите 'ℹ️ Помощь'",
            reply_markup=create_main_keyboard()
        )

if __name__ == "__main__":
    logger.info("Запуск бота...")
    try:
        bot.infinity_polling(none_stop=True)
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        raise