#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Улучшенный телеграм бот для управления чатами и рассылки сообщений
Поддерживает подключение нескольких чатов, проверку прав админа, медиа файлы
"""

import telebot
import sqlite3
import json
import logging
import os
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Union
from telebot import types
from telebot.apihelper import ApiTelegramException

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
                    chat_username TEXT,
                    member_count INTEGER DEFAULT 0,
                    bot_is_admin BOOLEAN DEFAULT 0,
                    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
    
    def add_chat(self, user_id: int, chat_id: int, chat_title: str, chat_type: str, 
                 chat_username: str = None, member_count: int = 0, bot_is_admin: bool = False):
        """Добавление чата к пользователю с расширенной информацией"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # Проверяем, нет ли уже такого чата
            cursor.execute('SELECT id FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
            if cursor.fetchone():
                # Обновляем информацию о существующем чате
                cursor.execute('''
                    UPDATE user_chats 
                    SET chat_title = ?, chat_type = ?, chat_username = ?, 
                        member_count = ?, bot_is_admin = ?, last_checked = CURRENT_TIMESTAMP,
                        is_active = 1
                    WHERE user_id = ? AND chat_id = ?
                ''', (chat_title, chat_type, chat_username, member_count, bot_is_admin, user_id, chat_id))
                conn.commit()
                return True, "Информация о чате обновлена"
            
            cursor.execute('''
                INSERT INTO user_chats (user_id, chat_id, chat_title, chat_type, chat_username, 
                                      member_count, bot_is_admin)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, chat_id, chat_title, chat_type, chat_username, member_count, bot_is_admin))
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
    
    def get_user_chats(self, user_id: int, only_admin: bool = False) -> List[Dict]:
        """Получение всех чатов пользователя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT chat_id, chat_title, chat_type, chat_username, member_count, 
                       bot_is_admin, added_at, last_checked, is_active
                FROM user_chats 
                WHERE user_id = ? AND is_active = 1
            '''
            
            if only_admin:
                query += ' AND bot_is_admin = 1'
                
            query += ' ORDER BY added_at DESC'
            
            cursor.execute(query, (user_id,))
            
            columns = ['chat_id', 'chat_title', 'chat_type', 'chat_username', 'member_count', 
                      'bot_is_admin', 'added_at', 'last_checked', 'is_active']
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
    
    def update_chat_admin_status(self, user_id: int, chat_id: int, is_admin: bool):
        """Обновление статуса администратора бота в чате"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE user_chats 
                SET bot_is_admin = ?, last_checked = CURRENT_TIMESTAMP
                WHERE user_id = ? AND chat_id = ?
            ''', (is_admin, user_id, chat_id))
            conn.commit()
    
    def get_user_statistics(self, user_id: int) -> Dict:
        """Получение статистики пользователя"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            
            # Общее количество чатов
            cursor.execute('SELECT COUNT(*) FROM user_chats WHERE user_id = ? AND is_active = 1', (user_id,))
            total_chats = cursor.fetchone()[0]
            
            # Количество чатов где бот админ
            cursor.execute('SELECT COUNT(*) FROM user_chats WHERE user_id = ? AND is_active = 1 AND bot_is_admin = 1', (user_id,))
            admin_chats = cursor.fetchone()[0]
            
            # Количество отправленных сообщений
            cursor.execute('SELECT COUNT(*), COALESCE(SUM(success_count), 0), COALESCE(SUM(failed_count), 0) FROM message_history WHERE user_id = ?', (user_id,))
            msg_stats = cursor.fetchone()
            
            # Статистика за последние 7 дней
            cursor.execute('''
                SELECT COUNT(*), COALESCE(SUM(success_count), 0) 
                FROM message_history 
                WHERE user_id = ? AND sent_at >= datetime('now', '-7 days')
            ''', (user_id,))
            week_stats = cursor.fetchone()
            
            return {
                'total_chats': total_chats,
                'admin_chats': admin_chats,
                'total_messages': msg_stats[0],
                'successful_sends': msg_stats[1],
                'failed_sends': msg_stats[2],
                'week_messages': week_stats[0],
                'week_successful': week_stats[1]
            }

# Инициализация базы данных
db = DatabaseManager(DB_NAME)

# Состояния пользователей
user_states = {}
user_messages = {}  # Хранение сообщений пользователей для пересылки

class UserStates:
    """Константы состояний пользователей"""
    WAITING_FOR_MESSAGE = "waiting_for_message"
    WAITING_FOR_CHAT_ID = "waiting_for_chat_id"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    NORMAL = "normal"

class ChatHelper:
    """Вспомогательные функции для работы с чатами"""
    
    @staticmethod
    def check_bot_admin_status(chat_id: int) -> tuple[bool, str]:
        """Проверка статуса администратора бота в чате"""
        try:
            bot_user = bot.get_me()
            chat_member = bot.get_chat_member(chat_id, bot_user.id)
            
            is_admin = chat_member.status in ['administrator', 'creator']
            
            if is_admin:
                # Проверяем права
                permissions = []
                if hasattr(chat_member, 'can_post_messages') and chat_member.can_post_messages:
                    permissions.append("отправка сообщений")
                if hasattr(chat_member, 'can_delete_messages') and chat_member.can_delete_messages:
                    permissions.append("удаление сообщений")
                if hasattr(chat_member, 'can_pin_messages') and chat_member.can_pin_messages:
                    permissions.append("закрепление сообщений")
                
                status_msg = f"✅ Бот является администратором"
                if permissions:
                    status_msg += f"\n🔑 Права: {', '.join(permissions)}"
                    
                return True, status_msg
            else:
                return False, f"❌ Бот не является администратором (статус: {chat_member.status})"
                
        except ApiTelegramException as e:
            if e.error_code == 400:
                return False, "❌ Бот не добавлен в чат или чат не существует"
            elif e.error_code == 403:
                return False, "❌ У бота нет доступа к чату"
            else:
                return False, f"❌ Ошибка проверки: {e.description}"
        except Exception as e:
            return False, f"❌ Неизвестная ошибка: {str(e)}"
    
    @staticmethod
    def get_chat_info(chat_id: int) -> Optional[Dict]:
        """Получение подробной информации о чате"""
        try:
            chat = bot.get_chat(chat_id)
            member_count = 0
            
            try:
                member_count = bot.get_chat_member_count(chat_id)
            except:
                pass
            
            return {
                'id': chat.id,
                'title': chat.title or f"Приватный чат {chat_id}",
                'type': chat.type,
                'username': getattr(chat, 'username', None),
                'member_count': member_count,
                'description': getattr(chat, 'description', None)
            }
        except Exception as e:
            logger.error(f"Error getting chat info for {chat_id}: {str(e)}")
            return None
    
    @staticmethod
    def format_chat_type(chat_type: str) -> str:
        """Форматирование типа чата для отображения"""
        type_map = {
            'private': '👤 Личный чат',
            'group': '👥 Группа',
            'supergroup': '👥 Супергруппа',
            'channel': '📢 Канал'
        }
        return type_map.get(chat_type, f'❓ {chat_type}')

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
        types.KeyboardButton("🔍 Проверить чаты"),
        types.KeyboardButton("📊 Статистика")
    )
    keyboard.add(
        types.KeyboardButton("⚙️ Настройки"),
        types.KeyboardButton("ℹ️ Помощь")
    )
    return keyboard

def create_message_type_keyboard():
    """Создание клавиатуры для выбора типа сообщения"""
    keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add(
        types.KeyboardButton("📄 Текстовое сообщение"),
        types.KeyboardButton("🖼️ Изображение")
    )
    keyboard.add(
        types.KeyboardButton("📁 Документ"),
        types.KeyboardButton("🎵 Аудио")
    )
    keyboard.add(
        types.KeyboardButton("🎥 Видео"),
        types.KeyboardButton("❌ Отмена")
    )
    return keyboard

def create_confirmation_keyboard():
    """Создание клавиатуры подтверждения"""
    keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add(
        types.KeyboardButton("✅ Отправить"),
        types.KeyboardButton("❌ Отмена")
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
        admin_status = "✅ Админ" if chat['bot_is_admin'] else "❌ Не админ"
        chat_type = ChatHelper.format_chat_type(chat['chat_type'])
        
        chat_list += f"{i}. {chat['chat_title']}\n"
        chat_list += f"   ID: {chat['chat_id']}\n"
        chat_list += f"   {chat_type}\n"
        chat_list += f"   Статус: {admin_status}\n"
        
        if chat['member_count'] > 0:
            chat_list += f"   👥 Участников: {chat['member_count']}\n"
        
        if chat['chat_username']:
            chat_list += f"   @{chat['chat_username']}\n"
            
        chat_list += f"   📅 Добавлен: {chat['added_at'][:16]}\n\n"
    
    # Создаем inline клавиатуру для быстрых действий
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔍 Проверить статус", callback_data="check_all_chats"))
    keyboard.add(types.InlineKeyboardButton("🔄 Обновить список", callback_data="refresh_chats"))
    
    bot.send_message(message.chat.id, chat_list, reply_markup=keyboard)

@bot.message_handler(func=lambda message: message.text == "➕ Добавить чат")
def add_chat_request(message):
    """Запрос на добавление чата"""
    user_states[message.from_user.id] = UserStates.WAITING_FOR_CHAT_ID
    
    instruction_text = """
➕ Добавление нового чата

🔧 Пошаговая инструкция:

1️⃣ Добавьте этого бота в нужный чат/канал
2️⃣ Назначьте бота администратором с правами:
   • Отправка сообщений
   • Удаление сообщений (опционально)
   • Закрепление сообщений (опционально)

3️⃣ Получите ID чата одним из способов:
   • Перешлите любое сообщение из чата боту @userinfobot
   • Для каналов: добавьте @userinfobot в канал
   • Используйте @RawDataBot

4️⃣ Отправьте ID чата в ответ на это сообщение

📝 Примеры форматов ID:
• Группа: -123456789
• Супергруппа: -1001234567890  
• Канал: -1001234567890

💡 Совет: ID всегда начинается с минуса для групп и каналов

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

@bot.message_handler(func=lambda message: message.text == "🔍 Проверить чаты")
def check_chats_status(message):
    """Проверить статус всех чатов пользователя"""
    user_chats = db.get_user_chats(message.from_user.id)
    
    if not user_chats:
        bot.send_message(
            message.chat.id,
            "У вас нет чатов для проверки.",
            reply_markup=create_main_keyboard()
        )
        return
    
    status_msg = bot.send_message(message.chat.id, "🔍 Проверяю статус чатов...")
    
    results = []
    updated_count = 0
    
    for chat in user_chats:
        chat_id = chat['chat_id']
        is_admin, status_text = ChatHelper.check_bot_admin_status(chat_id)
        
        # Обновляем статус в базе данных
        if chat['bot_is_admin'] != is_admin:
            db.update_chat_admin_status(message.from_user.id, chat_id, is_admin)
            updated_count += 1
        
        results.append(f"📋 {chat['chat_title']}\n{status_text}\n")
    
    report = "🔍 Результаты проверки:\n\n" + "\n".join(results)
    
    if updated_count > 0:
        report += f"\n✅ Обновлено статусов: {updated_count}"
    
    bot.edit_message_text(report, message.chat.id, status_msg.message_id)

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    """Показать расширенную статистику пользователя"""
    stats = db.get_user_statistics(message.from_user.id)
    
    stats_text = f"""
📊 Ваша подробная статистика:

👥 Чаты:
  • Всего подключено: {stats['total_chats']}
  • Бот является админом: {stats['admin_chats']}
  • Доступно для рассылки: {stats['admin_chats']}/{stats['total_chats']}

📝 Сообщения:
  • Всего отправлено: {stats['total_messages']}
  • Успешных доставок: {stats['successful_sends']}
  • Неудачных попыток: {stats['failed_sends']}

📅 За последние 7 дней:
  • Сообщений отправлено: {stats['week_messages']}
  • Успешных доставок: {stats['week_successful']}

📈 Эффективность:
"""
    
    if stats['total_messages'] > 0:
        success_rate = (stats['successful_sends'] / (stats['successful_sends'] + stats['failed_sends'])) * 100
        stats_text += f"  • Успешность доставки: {success_rate:.1f}%\n"
    
    if stats['total_chats'] > 0:
        admin_rate = (stats['admin_chats'] / stats['total_chats']) * 100
        stats_text += f"  • Чатов с правами админа: {admin_rate:.1f}%"
    
    stats_text += "\n\n💡 Совет: регулярно проверяйте статус чатов для лучшей доставляемости."
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔍 Проверить чаты", callback_data="check_all_chats"))
    
    bot.send_message(message.chat.id, stats_text, reply_markup=keyboard)

@bot.message_handler(func=lambda message: message.text == "❌ Отмена")
def cancel_operation(message):
    """Отмена текущей операции"""
    user_states.pop(message.from_user.id, None)
    bot.send_message(
        message.chat.id,
        "❌ Операция отменена.",
        reply_markup=create_main_keyboard()
    )

@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
def settings_menu(message):
    """Меню настроек"""
    settings_text = """
⚙️ Настройки бота:

Здесь вы можете настроить различные параметры работы бота.
"""
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔔 Уведомления", callback_data="settings_notifications"))
    keyboard.add(types.InlineKeyboardButton("⏰ Задержка между сообщениями", callback_data="settings_delay"))
    keyboard.add(types.InlineKeyboardButton("📊 Экспорт данных", callback_data="settings_export"))
    keyboard.add(types.InlineKeyboardButton("🗑️ Очистить историю", callback_data="settings_clear"))
    
    bot.send_message(message.chat.id, settings_text, reply_markup=keyboard)

@bot.message_handler(func=lambda message: message.text == "ℹ️ Помощь")
def help_button(message):
    """Обработчик кнопки помощи"""
    help_command(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_all_chats'))
def check_all_chats_callback(call):
    """Callback для проверки всех чатов"""
    check_chats_status(call.message)
    bot.answer_callback_query(call.id, "Проверяю статус чатов...")

@bot.callback_query_handler(func=lambda call: call.data.startswith('refresh_chats'))
def refresh_chats_callback(call):
    """Callback для обновления списка чатов"""
    # Имитируем нажатие кнопки "Мои чаты"
    fake_message = call.message
    fake_message.from_user = call.from_user
    show_user_chats(fake_message)
    bot.answer_callback_query(call.id, "Список обновлен!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('settings_'))
def settings_callback(call):
    """Обработчик настроек"""
    setting = call.data.split('_')[1]
    
    if setting == "notifications":
        bot.answer_callback_query(call.id, "Функция в разработке")
    elif setting == "delay":
        bot.answer_callback_query(call.id, "Функция в разработке") 
    elif setting == "export":
        bot.answer_callback_query(call.id, "Функция в разработке")
    elif setting == "clear":
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("✅ Да, очистить", callback_data="confirm_clear_history"),
            types.InlineKeyboardButton("❌ Отмена", callback_data="cancel_clear")
        )
        bot.edit_message_text(
            "⚠️ Вы уверены, что хотите очистить всю историю сообщений?\nЭто действие нельзя отменить!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard
        )

@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    """Обработчик всех остальных сообщений"""
    user_id = message.from_user.id
    user_state = user_states.get(user_id, UserStates.NORMAL)
    
    if user_state == UserStates.WAITING_FOR_CHAT_ID:
        # Обработка добавления чата
        try:
            chat_id = int(message.text.strip())
            
            # Получаем информацию о чате
            chat_info = ChatHelper.get_chat_info(chat_id)
            
            if not chat_info:
                bot.send_message(
                    message.chat.id,
                    "❌ Не удалось получить информацию о чате.\n\n"
                    "🔧 Возможные причины:\n"
                    "• Бот не добавлен в чат\n"
                    "• Неверный ID чата\n"
                    "• Чат не существует\n"
                    "• Бот заблокирован в чате",
                    reply_markup=create_main_keyboard()
                )
                user_states.pop(user_id, None)
                return
            
            # Проверяем права администратора
            is_admin, admin_status = ChatHelper.check_bot_admin_status(chat_id)
            
            # Добавляем чат в базу данных
            success, result_message = db.add_chat(
                user_id, 
                chat_id, 
                chat_info['title'], 
                chat_info['type'],
                chat_info.get('username'),
                chat_info.get('member_count', 0),
                is_admin
            )
            
            # Формируем ответное сообщение
            response = f"{'✅' if success else '⚠️'} {result_message}\n\n"
            response += f"📋 Информация о чате:\n"
            response += f"• Название: {chat_info['title']}\n"
            response += f"• ID: {chat_id}\n"
            response += f"• Тип: {ChatHelper.format_chat_type(chat_info['type'])}\n"
            
            if chat_info.get('username'):
                response += f"• Username: @{chat_info['username']}\n"
                
            if chat_info.get('member_count', 0) > 0:
                response += f"• Участников: {chat_info['member_count']}\n"
            
            response += f"\n🔐 Статус бота:\n{admin_status}"
            
            if not is_admin:
                response += "\n\n⚠️ Рекомендация: назначьте бота администратором для корректной работы рассылки."
            
            bot.send_message(message.chat.id, response, reply_markup=create_main_keyboard())
                
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ Неверный формат ID чата.\n\n"
                "📝 Правильные форматы:\n"
                "• Группа: -123456789\n"
                "• Супергруппа: -1001234567890\n"
                "• Канал: -1001234567890\n\n"
                "💡 ID всегда начинается с минуса для групп и каналов",
                reply_markup=create_cancel_keyboard()
            )
            return
        except Exception as e:
            logger.error(f"Error adding chat {message.text}: {str(e)}")
            bot.send_message(
                message.chat.id,
                f"❌ Произошла ошибка при добавлении чата:\n{str(e)}\n\n"
                "Попробуйте еще раз или обратитесь к администратору.",
                reply_markup=create_main_keyboard()
            )
        
        user_states.pop(user_id, None)
        
    elif user_state == UserStates.WAITING_FOR_MESSAGE:
        # Обработка отправки сообщения (поддержка разных типов)
        user_chats = db.get_user_chats(user_id, only_admin=True)  # Только чаты где бот админ
        
        if not user_chats:
            all_chats = db.get_user_chats(user_id)
            if not all_chats:
                bot.send_message(
                    message.chat.id,
                    "❌ У вас нет подключенных чатов.",
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "❌ У вас нет чатов где бот является администратором.\n"
                    "Используйте '🔍 Проверить чаты' для обновления статусов.",
                    reply_markup=create_main_keyboard()
                )
            user_states.pop(user_id, None)
            return
        
        # Сохраняем сообщение для отправки
        user_messages[user_id] = message
        
        # Показываем превью и запрашиваем подтверждение
        preview_text = f"📋 Готово к отправке в {len(user_chats)} чат(ов):\n\n"
        
        # Показываем список чатов
        for i, chat in enumerate(user_chats[:5], 1):
            preview_text += f"{i}. {chat['chat_title']}\n"
        
        if len(user_chats) > 5:
            preview_text += f"... и еще {len(user_chats) - 5} чатов\n"
        
        preview_text += f"\n📝 Содержимое:\n"
        
        # Определяем тип сообщения
        if message.content_type == 'text':
            preview_text += f"Текст: {message.text[:100]}"
            if len(message.text) > 100:
                preview_text += "..."
        elif message.content_type == 'photo':
            preview_text += "🖼️ Изображение"
            if message.caption:
                preview_text += f" с подписью: {message.caption[:50]}"
                if len(message.caption) > 50:
                    preview_text += "..."
        elif message.content_type == 'document':
            preview_text += f"📁 Документ: {message.document.file_name or 'файл'}"
        elif message.content_type == 'video':
            preview_text += "🎥 Видео"
        elif message.content_type == 'audio':
            preview_text += "🎵 Аудио"
        elif message.content_type == 'voice':
            preview_text += "🎤 Голосовое сообщение"
        else:
            preview_text += f"📎 {message.content_type}"
        
        preview_text += "\n\n✅ Подтвердите отправку:"
        
        user_states[user_id] = UserStates.WAITING_FOR_CONFIRMATION
        bot.send_message(message.chat.id, preview_text, reply_markup=create_confirmation_keyboard())
        
    elif user_state == UserStates.WAITING_FOR_CONFIRMATION:
        if message.text == "✅ Отправить":
            # Выполняем массовую рассылку
            original_message = user_messages.get(user_id)
            if not original_message:
                bot.send_message(
                    message.chat.id,
                    "❌ Ошибка: сообщение не найдено. Попробуйте еще раз.",
                    reply_markup=create_main_keyboard()
                )
                user_states.pop(user_id, None)
                return
            
            user_chats = db.get_user_chats(user_id, only_admin=True)
            
            status_message = bot.send_message(
                message.chat.id,
                f"📤 Отправляю сообщение в {len(user_chats)} чат(ов)..."
            )
            
            success_count = 0
            failed_count = 0
            failed_chats = []
            
            # Функция для отправки разных типов сообщений
            def send_message_to_chat(chat_id, msg):
                if msg.content_type == 'text':
                    return bot.send_message(chat_id, msg.text)
                elif msg.content_type == 'photo':
                    return bot.send_photo(chat_id, msg.photo[-1].file_id, caption=msg.caption)
                elif msg.content_type == 'document':
                    return bot.send_document(chat_id, msg.document.file_id, caption=msg.caption)
                elif msg.content_type == 'video':
                    return bot.send_video(chat_id, msg.video.file_id, caption=msg.caption)
                elif msg.content_type == 'audio':
                    return bot.send_audio(chat_id, msg.audio.file_id, caption=msg.caption)
                elif msg.content_type == 'voice':
                    return bot.send_voice(chat_id, msg.voice.file_id)
                elif msg.content_type == 'video_note':
                    return bot.send_video_note(chat_id, msg.video_note.file_id)
                elif msg.content_type == 'sticker':
                    return bot.send_sticker(chat_id, msg.sticker.file_id)
                else:
                    raise Exception(f"Неподдерживаемый тип сообщения: {msg.content_type}")
            
            # Отправляем сообщение во все чаты с небольшой задержкой
            for i, chat in enumerate(user_chats):
                try:
                    send_message_to_chat(chat['chat_id'], original_message)
                    success_count += 1
                    
                    # Небольшая задержка между отправками для избежания лимитов
                    if i < len(user_chats) - 1:
                        time.sleep(0.1)
                        
                except Exception as e:
                    failed_count += 1
                    error_msg = str(e)
                    if "Forbidden" in error_msg:
                        error_msg = "Бот заблокирован или удален из чата"
                    elif "Bad Request" in error_msg:
                        error_msg = "Неверный запрос или файл недоступен"
                    
                    failed_chats.append(f"{chat['chat_title']}: {error_msg}")
                    logger.error(f"Failed to send message to {chat['chat_id']}: {str(e)}")
            
            # Сохраняем историю
            chat_ids = [chat['chat_id'] for chat in user_chats]
            message_content = original_message.text or f"[{original_message.content_type}]"
            db.save_message_history(user_id, message_content, chat_ids, success_count, failed_count)
            
            # Отправляем отчет
            report = f"📊 Отчет о рассылке:\n\n"
            report += f"✅ Успешно отправлено: {success_count}\n"
            report += f"❌ Не удалось отправить: {failed_count}\n"
            
            if success_count > 0:
                success_rate = (success_count / (success_count + failed_count)) * 100
                report += f"📈 Успешность: {success_rate:.1f}%\n"
            
            if failed_chats:
                report += f"\n🚫 Ошибки:\n"
                for error in failed_chats[:3]:  # Показываем только первые 3 ошибки
                    report += f"• {error}\n"
                if len(failed_chats) > 3:
                    report += f"... и еще {len(failed_chats) - 3} ошибок"
            
            bot.edit_message_text(report, message.chat.id, status_message.message_id)
            
            # Очищаем состояние
            user_states.pop(user_id, None)
            user_messages.pop(user_id, None)
            
            # Возвращаем главную клавиатуру
            bot.send_message(
                message.chat.id,
                "✅ Рассылка завершена! Что делаем дальше?",
                reply_markup=create_main_keyboard()
            )
        else:
            # Отмена отправки
            user_states.pop(user_id, None)
            user_messages.pop(user_id, None)
            bot.send_message(
                message.chat.id,
                "❌ Отправка отменена.",
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