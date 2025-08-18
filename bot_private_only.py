#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Улучшенный телеграм бот - ТОЛЬКО ЛИЧНЫЕ СООБЩЕНИЯ
В групповых чатах бот полностью молчит!
Улучшенная система приема ID чатов через пересылку
"""

import telebot
import sqlite3
import json
import logging
import os
import time
import threading
from datetime import datetime
from typing import List, Dict, Optional
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

# Токен бота
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("Необходимо установить переменную окружения BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN)
DB_NAME = 'telegram_bot.db'

# Состояния пользователей
user_states = {}
user_messages = {}

class UserStates:
    WAITING_FOR_MESSAGE = "waiting_for_message"
    WAITING_FOR_CHAT_ID = "waiting_for_chat_id"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    NORMAL = "normal"

class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
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
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name))
            conn.commit()
    
    def add_chat(self, user_id: int, chat_id: int, chat_title: str, chat_type: str, 
                 chat_username: str = None, member_count: int = 0, bot_is_admin: bool = False):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
            if cursor.fetchone():
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
    
    def get_user_chats(self, user_id: int, only_admin: bool = False) -> List[Dict]:
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
    
    def remove_chat(self, user_id: int, chat_id: int):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM user_chats WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

db = DatabaseManager(DB_NAME)

def is_private_chat(message) -> bool:
    return message.chat.type == 'private'

def private_chat_only(func):
    def wrapper(message):
        if not is_private_chat(message):
            return  # Молчим в группах
        return func(message)
    return wrapper

def get_chat_type_emoji(chat_type: str) -> str:
    type_map = {
        'private': '👤 Личный чат',
        'group': '👥 Группа', 
        'supergroup': '👥 Супергруппа',
        'channel': '📢 Канал'
    }
    return type_map.get(chat_type, f'❓ {chat_type}')

def check_bot_admin_status(chat_id: int) -> tuple:
    try:
        bot_user = bot.get_me()
        chat_member = bot.get_chat_member(chat_id, bot_user.id)
        
        is_admin = chat_member.status in ['administrator', 'creator']
        
        if is_admin:
            status_msg = "✅ Бот является администратором"
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

def get_chat_info(chat_id: int) -> Optional[Dict]:
    try:
        chat = bot.get_chat(chat_id)
        member_count = 0
        
        try:
            member_count = bot.get_chat_member_count(chat_id)
        except:
            pass
        
        return {
            'id': chat.id,
            'title': chat.title or f"Чат {chat_id}",
            'type': chat.type,
            'username': getattr(chat, 'username', None),
            'member_count': member_count,
            'description': getattr(chat, 'description', None)
        }
    except Exception as e:
        logger.error(f"Error getting chat info for {chat_id}: {str(e)}")
        return None

def create_main_keyboard():
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
        types.KeyboardButton("ℹ️ Помощь")
    )
    return keyboard

def create_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    return keyboard

# ОБРАБОТЧИК ДОБАВЛЕНИЯ БОТА В ЧАТ
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_member(message):
    """Автоматическое определение ID при добавлении бота в чат"""
    bot_user = bot.get_me()
    for member in message.new_chat_members:
        if member.id == bot_user.id:
            chat_info = {
                'id': message.chat.id,
                'title': message.chat.title or f"Чат {message.chat.id}",
                'type': message.chat.type
            }
            
            # Уведомляем того, кто добавил бота
            if message.from_user and message.chat.type != 'channel':
                try:
                    notification_text = f"""
🎉 **Бот добавлен в чат!**

📋 **Информация:**
• **Название:** {chat_info['title']}
• **ID:** `{chat_info['id']}`
• **Тип:** {get_chat_type_emoji(chat_info['type'])}

✅ **Что делать дальше:**
1. Сделайте бота администратором
2. Откройте личные сообщения с ботом
3. Используйте "➕ Добавить чат"
4. Отправьте ID: `{chat_info['id']}`

💡 **Или перешлите любое сообщение из этого чата боту в ЛС!**
"""
                    
                    bot.send_message(message.from_user.id, notification_text, parse_mode='Markdown')
                except:
                    # Если ЛС недоступны, отправляем в чат один раз
                    bot.send_message(
                        message.chat.id,
                        f"👋 Привет! Я добавлен в чат.\n\n"
                        f"📋 ID этого чата: `{message.chat.id}`\n\n"
                        f"💡 Для управления рассылками напишите мне в ЛС: @{bot_user.username}",
                        parse_mode='Markdown'
                    )
            break

# КОМАНДЫ - ТОЛЬКО В ЛС
@bot.message_handler(commands=['start'])
@private_chat_only
def start_command(message):
    user = message.from_user
    db.add_user(user.id, user.username, user.first_name, user.last_name)
    
    welcome_text = f"""
👋 **Добро пожаловать, {user.first_name}!**

Этот бот поможет управлять чатами и отправлять массовые рассылки.

🔧 **Основные возможности:**
• Подключение неограниченного количества чатов
• Умная массовая рассылка всех типов медиа
• Автоматическое определение ID чатов
• Детальная аналитика и мониторинг

🚀 **Быстрый старт:**
1. Добавьте бота в нужные чаты как администратора
2. Нажмите "➕ Добавить чат"
3. Перешлите сообщение из чата или отправьте ID
4. Начинайте рассылки через "📝 Отправить сообщение"

💡 **Важно:** Все управление происходит только в личных сообщениях!
"""
    
    bot.send_message(message.chat.id, welcome_text, 
                    reply_markup=create_main_keyboard(), parse_mode='Markdown')

@bot.message_handler(commands=['help'])
@private_chat_only  
def help_command(message):
    help_text = """
🆘 **Помощь по использованию бота:**

**ВАЖНО:** Бот работает только в личных сообщениях!

📝 **Отправить сообщение** - массовая рассылка во все чаты
📋 **Мои чаты** - список подключенных чатов  
➕ **Добавить чат** - подключить новый чат
❌ **Удалить чат** - отключить чат от рассылок
🔍 **Проверить чаты** - проверить статус бота в чатах
ℹ️ **Помощь** - показать эту справку

🎯 **Как добавить чат (3 способа):**

**СПОСОБ 1 (Самый простой):**
• Добавьте бота в чат как администратора
• Перешлите любое сообщение из того чата сюда
• Бот автоматически определит ID и предложит добавить

**СПОСОБ 2:**
• Нажмите "➕ Добавить чат"
• Отправьте ID чата числом (например: -1001234567890)

**СПОСОБ 3:**
• При добавлении бота в чат он покажет свой ID
• Скопируйте и используйте этот ID

⚠️ **Требования:**
• Бот должен быть администратором в чатах
• Права: отправка сообщений (обязательно)
• В групповых чатах бот не отвечает на команды
"""
    
    bot.send_message(message.chat.id, help_text, parse_mode='Markdown')

# КНОПКИ - ТОЛЬКО В ЛС
@bot.message_handler(func=lambda message: message.text == "📋 Мои чаты")
@private_chat_only
def show_user_chats(message):
    user_chats = db.get_user_chats(message.from_user.id)
    
    if not user_chats:
        bot.send_message(
            message.chat.id, 
            "У вас пока нет подключенных чатов.\n\n"
            "Используйте '➕ Добавить чат' или перешлите сообщение из нужного чата.",
            reply_markup=create_main_keyboard()
        )
        return
    
    chat_list = "📋 **Ваши чаты:**\n\n"
    for i, chat in enumerate(user_chats, 1):
        admin_status = "✅ Админ" if chat['bot_is_admin'] else "❌ Не админ"
        chat_type = get_chat_type_emoji(chat['chat_type'])
        
        chat_list += f"{i}. **{chat['chat_title']}**\n"
        chat_list += f"   ID: `{chat['chat_id']}`\n"
        chat_list += f"   {chat_type}\n"
        chat_list += f"   Статус: {admin_status}\n"
        
        if chat['member_count'] > 0:
            chat_list += f"   👥 Участников: {chat['member_count']}\n"
        
        if chat['chat_username']:
            chat_list += f"   @{chat['chat_username']}\n"
            
        chat_list += f"   📅 Добавлен: {chat['added_at'][:16]}\n\n"
    
    bot.send_message(message.chat.id, chat_list, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "➕ Добавить чат")
@private_chat_only
def add_chat_request(message):
    user_states[message.from_user.id] = UserStates.WAITING_FOR_CHAT_ID
    
    instruction_text = """
➕ **Добавление нового чата**

🎯 **Выберите удобный способ:**

**СПОСОБ 1 (Рекомендуемый):**
• Перешлите любое сообщение из целевого чата сюда
• Бот автоматически определит ID и информацию о чате

**СПОСОБ 2:**  
• Отправьте ID чата числом
• Примеры: `-123456789` или `-1001234567890`

**СПОСОБ 3:**
• Используйте @userinfobot в целевом чате
• Скопируйте ID и отправьте сюда

💡 **Подсказки:**
• ID групп и каналов всегда отрицательные
• Бот должен быть администратором в чате
• Пересылка сообщения - самый простой способ!

**Отправьте ID чата или перешлите сообщение:**
"""
    
    bot.send_message(message.chat.id, instruction_text, 
                    reply_markup=create_cancel_keyboard(), parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "❌ Отмена")
@private_chat_only
def cancel_operation(message):
    user_states.pop(message.from_user.id, None)
    user_messages.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "❌ Операция отменена.", reply_markup=create_main_keyboard())

# ЗАГЛУШКА ДЛЯ ГРУППОВЫХ ЧАТОВ
@bot.message_handler(func=lambda message: message.chat.type != 'private')
def ignore_group_messages(message):
    """Полностью игнорируем сообщения в групповых чатах"""
    pass

# ОСНОВНОЙ ОБРАБОТЧИК - ТОЛЬКО ЛС
@bot.message_handler(func=lambda message: True)
@private_chat_only
def handle_private_messages(message):
    user_id = message.from_user.id
    user_state = user_states.get(user_id, UserStates.NORMAL)
    
    if user_state == UserStates.WAITING_FOR_CHAT_ID:
        chat_id = None
        source_info = ""
        
        # Проверяем пересылку из чата
        if message.forward_from_chat:
            chat_id = message.forward_from_chat.id
            chat_title = message.forward_from_chat.title or f"Чат {chat_id}"
            chat_type = message.forward_from_chat.type
            source_info = f"из пересланного сообщения"
            
            # Сразу предлагаем добавить
            response = f"""
✅ **Чат определен автоматически!**

📋 **Информация:**
• **Название:** {chat_title}
• **ID:** `{chat_id}`
• **Тип:** {get_chat_type_emoji(chat_type)}
• **Источник:** {source_info}

❓ **Добавить этот чат для рассылок?**
"""
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(
                types.InlineKeyboardButton("✅ Да, добавить", callback_data=f"add_chat_{chat_id}"),
                types.InlineKeyboardButton("❌ Нет", callback_data="cancel_add")
            )
            
            bot.send_message(message.chat.id, response, 
                            reply_markup=keyboard, parse_mode='Markdown')
            user_states.pop(user_id, None)
            return
            
        elif message.text and message.text.strip().lstrip('-').isdigit():
            # Проверяем ID чата
            try:
                chat_id = int(message.text.strip())
                if chat_id < 0:  # Групповой чат
                    source_info = "из введенного ID"
                    
                    response = f"""
🎯 **ID чата получен:** `{chat_id}`

❓ **Добавить этот чат для рассылок?**
"""
                    
                    keyboard = types.InlineKeyboardMarkup()
                    keyboard.add(
                        types.InlineKeyboardButton("✅ Да, добавить", callback_data=f"add_chat_{chat_id}"),
                        types.InlineKeyboardButton("❌ Нет", callback_data="cancel_add")
                    )
                    
                    bot.send_message(message.chat.id, response, 
                                    reply_markup=keyboard, parse_mode='Markdown')
                    user_states.pop(user_id, None)
                    return
            except:
                pass
        
        # Неподходящий формат
        bot.send_message(
            message.chat.id,
            "❌ **Неподдерживаемый формат**\n\n"
            "Отправьте:\n"
            "• **Пересланное сообщение** из целевого чата\n"
            "• **ID чата числом** (например: `-1001234567890`)\n\n"
            "Или нажмите '❌ Отмена'",
            reply_markup=create_cancel_keyboard(),
            parse_mode='Markdown'
        )
        return
    
    # Обычные сообщения - проверяем на пересылку или ID
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
        chat_title = message.forward_from_chat.title or f"Чат {chat_id}"
        chat_type = message.forward_from_chat.type
        
        response = f"""
✅ **Обнаружен чат из пересылки!**

📋 **Информация:**
• **Название:** {chat_title}
• **ID:** `{chat_id}`
• **Тип:** {get_chat_type_emoji(chat_type)}

❓ **Добавить этот чат для рассылок?**
"""
        
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("✅ Да, добавить", callback_data=f"add_chat_{chat_id}"),
            types.InlineKeyboardButton("❌ Нет", callback_data="cancel_add")
        )
        
        bot.send_message(message.chat.id, response, 
                        reply_markup=keyboard, parse_mode='Markdown')
        return
    
    elif message.text and message.text.strip().lstrip('-').isdigit():
        try:
            chat_id = int(message.text.strip())
            if chat_id < 0:
                response = f"""
🎯 **Обнаружен ID чата:** `{chat_id}`

❓ **Добавить этот чат для рассылок?**
"""
                
                keyboard = types.InlineKeyboardMarkup()
                keyboard.add(
                    types.InlineKeyboardButton("✅ Да, добавить", callback_data=f"add_chat_{chat_id}"),
                    types.InlineKeyboardButton("❌ Нет", callback_data="cancel_add")
                )
                
                bot.send_message(message.chat.id, response, 
                                reply_markup=keyboard, parse_mode='Markdown')
                return
        except:
            pass
    
    # Обычное сообщение
    bot.send_message(
        message.chat.id,
        "🤖 Используйте кнопки меню для управления ботом.\n\n"
        "💡 **Для добавления чата:**\n"
        "• Нажмите '➕ Добавить чат'\n"
        "• Или перешлите сообщение из нужного чата\n\n"
        "📋 Все функции доступны через кнопки меню.",
        reply_markup=create_main_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_chat_'))
def add_chat_callback(call):
    try:
        chat_id = int(call.data.split('_')[2])
        user_id = call.from_user.id
        
        # Получаем информацию о чате
        chat_info = get_chat_info(chat_id)
        
        if not chat_info:
            bot.edit_message_text(
                "❌ **Не удалось получить информацию о чате**\n\n"
                "Возможные причины:\n"
                "• Бот не добавлен в чат\n"
                "• Неверный ID чата\n"
                "• Чат не существует",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='Markdown'
            )
            bot.answer_callback_query(call.id, "❌ Ошибка получения информации о чате")
            return
        
        # Проверяем права администратора
        is_admin, admin_status = check_bot_admin_status(chat_id)
        
        # Добавляем в базу данных
        success, result_message = db.add_chat(
            user_id, chat_id, chat_info['title'], chat_info['type'],
            chat_info.get('username'), chat_info.get('member_count', 0), is_admin
        )
        
        if success:
            response = f"✅ **{result_message}**\n\n"
            response += f"📋 **Информация о чате:**\n"
            response += f"• **Название:** {chat_info['title']}\n"
            response += f"• **ID:** `{chat_id}`\n"
            response += f"• **Тип:** {get_chat_type_emoji(chat_info['type'])}\n"
            
            if chat_info.get('username'):
                response += f"• **Username:** @{chat_info['username']}\n"
                
            if chat_info.get('member_count', 0) > 0:
                response += f"• **Участников:** {chat_info['member_count']}\n"
            
            response += f"\n🔐 **Статус бота:**\n{admin_status}"
            
            if not is_admin:
                response += "\n\n⚠️ **Рекомендация:** Назначьте бота администратором для корректной работы рассылки."
            else:
                response += "\n\n✅ **Отлично!** Чат готов для рассылки сообщений."
            
            bot.edit_message_text(response, call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            bot.answer_callback_query(call.id, "✅ Чат добавлен!")
        else:
            bot.edit_message_text(f"❌ {result_message}", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "❌ Ошибка при добавлении")
        
    except Exception as e:
        logger.error(f"Error in add_chat_callback: {str(e)}")
        bot.answer_callback_query(call.id, f"❌ Ошибка: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_add')
def cancel_add_callback(call):
    bot.edit_message_text(
        "❌ Добавление чата отменено.",
        call.message.chat.id, 
        call.message.message_id
    )
    bot.answer_callback_query(call.id, "Отменено")

if __name__ == "__main__":
    logger.info("🚀 Запуск улучшенного бота (только ЛС)...")
    
    try:
        logger.info("✅ Бот запущен успешно")
        logger.info("📋 Режим работы: только личные сообщения")
        logger.info("🔇 В групповых чатах бот полностью молчит")
        logger.info("🎯 Поддержка автоматического определения ID через пересылку")
        
        bot.infinity_polling(none_stop=True)
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        raise
