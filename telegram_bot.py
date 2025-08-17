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
import queue
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Union, Tuple
from telebot import types
from telebot.apihelper import ApiTelegramException
from concurrent.futures import ThreadPoolExecutor
import re

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

# Глобальные переменные
user_states = {}
user_messages = {}  # Хранение сообщений пользователей для пересылки
message_queue = queue.Queue()  # Очередь сообщений для рассылки
active_broadcasts = {}  # Активные рассылки по пользователям

class UserStates:
    """Константы состояний пользователей"""
    WAITING_FOR_MESSAGE = "waiting_for_message"
    WAITING_FOR_CHAT_ID = "waiting_for_chat_id"
    WAITING_FOR_CONFIRMATION = "waiting_for_confirmation"
    WAITING_FOR_CHAT_FILTER = "waiting_for_chat_filter"
    NORMAL = "normal"

class BroadcastManager:
    """Класс для управления массовыми рассылками"""
    
    def __init__(self):
        self.active_broadcasts = {}
        self.executor = ThreadPoolExecutor(max_workers=3)
        
    def start_broadcast(self, user_id: int, message, chats: List[Dict], 
                       status_message_id: int, chat_id: int) -> str:
        """Запуск массовой рассылки в отдельном потоке"""
        broadcast_id = f"{user_id}_{int(time.time())}"
        
        broadcast_info = {
            'id': broadcast_id,
            'user_id': user_id,
            'status': 'running',
            'total_chats': len(chats),
            'sent_count': 0,
            'failed_count': 0,
            'start_time': time.time(),
            'status_message_id': status_message_id,
            'chat_id': chat_id,
            'failed_chats': []
        }
        
        self.active_broadcasts[broadcast_id] = broadcast_info
        
        # Запускаем рассылку в отдельном потоке
        future = self.executor.submit(
            self._execute_broadcast, 
            broadcast_id, message, chats
        )
        
        return broadcast_id
    
    def _execute_broadcast(self, broadcast_id: str, message, chats: List[Dict]):
        """Выполнение рассылки с контролем скорости"""
        broadcast_info = self.active_broadcasts.get(broadcast_id)
        if not broadcast_info:
            return
            
        try:
            for i, chat in enumerate(chats):
                if broadcast_info['status'] != 'running':
                    break
                    
                try:
                    # Отправляем сообщение
                    self._send_message_to_chat(chat['chat_id'], message)
                    broadcast_info['sent_count'] += 1
                    
                    # Обновляем прогресс каждые 5 сообщений
                    if (i + 1) % 5 == 0 or i == len(chats) - 1:
                        self._update_progress(broadcast_id)
                    
                    # Задержка между отправками
                    delay = self._calculate_delay(i, len(chats))
                    if delay > 0:
                        time.sleep(delay)
                        
                except Exception as e:
                    broadcast_info['failed_count'] += 1
                    error_msg = self._format_error(str(e))
                    broadcast_info['failed_chats'].append({
                        'chat_title': chat['chat_title'],
                        'error': error_msg
                    })
                    logger.error(f"Failed to send to {chat['chat_id']}: {str(e)}")
            
            # Завершаем рассылку
            broadcast_info['status'] = 'completed'
            broadcast_info['end_time'] = time.time()
            self._send_final_report(broadcast_id)
            
        except Exception as e:
            broadcast_info['status'] = 'failed'
            broadcast_info['error'] = str(e)
            logger.error(f"Broadcast {broadcast_id} failed: {str(e)}")
        finally:
            # Удаляем из активных через 5 минут
            threading.Timer(300, lambda: self.active_broadcasts.pop(broadcast_id, None)).start()
    
    def _send_message_to_chat(self, chat_id: int, message):
        """Отправка сообщения в чат с обработкой типов"""
        if message.content_type == 'text':
            return bot.send_message(chat_id, message.text, parse_mode='HTML')
        elif message.content_type == 'photo':
            return bot.send_photo(chat_id, message.photo[-1].file_id, 
                                caption=message.caption, parse_mode='HTML')
        elif message.content_type == 'document':
            return bot.send_document(chat_id, message.document.file_id, 
                                   caption=message.caption, parse_mode='HTML')
        elif message.content_type == 'video':
            return bot.send_video(chat_id, message.video.file_id, 
                                caption=message.caption, parse_mode='HTML')
        elif message.content_type == 'audio':
            return bot.send_audio(chat_id, message.audio.file_id, 
                                caption=message.caption, parse_mode='HTML')
        elif message.content_type == 'voice':
            return bot.send_voice(chat_id, message.voice.file_id)
        elif message.content_type == 'video_note':
            return bot.send_video_note(chat_id, message.video_note.file_id)
        elif message.content_type == 'sticker':
            return bot.send_sticker(chat_id, message.sticker.file_id)
        elif message.content_type == 'animation':
            return bot.send_animation(chat_id, message.animation.file_id,
                                    caption=message.caption, parse_mode='HTML')
        else:
            raise Exception(f"Неподдерживаемый тип сообщения: {message.content_type}")
    
    def _calculate_delay(self, current_index: int, total_count: int) -> float:
        """Вычисление задержки между отправками"""
        if total_count <= 10:
            return 0.1  # Минимальная задержка для малых рассылок
        elif total_count <= 50:
            return 0.2  # Средняя задержка
        else:
            return 0.3  # Максимальная задержка для больших рассылок
    
    def _format_error(self, error_str: str) -> str:
        """Форматирование ошибок для пользователя"""
        if "Forbidden" in error_str:
            return "Бот заблокирован или удален"
        elif "Bad Request" in error_str:
            if "chat not found" in error_str.lower():
                return "Чат не найден"
            elif "not enough rights" in error_str.lower():
                return "Недостаточно прав"
            else:
                return "Неверный запрос"
        elif "Too Many Requests" in error_str:
            return "Превышен лимит запросов"
        elif "Network" in error_str:
            return "Проблемы с сетью"
        else:
            return "Неизвестная ошибка"
    
    def _update_progress(self, broadcast_id: str):
        """Обновление прогресса рассылки"""
        broadcast_info = self.active_broadcasts.get(broadcast_id)
        if not broadcast_info:
            return
            
        try:
            progress = (broadcast_info['sent_count'] + broadcast_info['failed_count']) / broadcast_info['total_chats'] * 100
            
            status_text = f"📤 Рассылка в процессе...\n\n"
            status_text += f"📊 Прогресс: {progress:.1f}%\n"
            status_text += f"✅ Отправлено: {broadcast_info['sent_count']}\n"
            status_text += f"❌ Ошибок: {broadcast_info['failed_count']}\n"
            status_text += f"📋 Всего чатов: {broadcast_info['total_chats']}"
            
            bot.edit_message_text(
                status_text,
                broadcast_info['chat_id'],
                broadcast_info['status_message_id']
            )
        except Exception as e:
            logger.error(f"Failed to update progress for {broadcast_id}: {str(e)}")
    
    def _send_final_report(self, broadcast_id: str):
        """Отправка финального отчета"""
        broadcast_info = self.active_broadcasts.get(broadcast_id)
        if not broadcast_info:
            return
            
        try:
            duration = time.time() - broadcast_info['start_time']
            success_rate = (broadcast_info['sent_count'] / broadcast_info['total_chats']) * 100
            
            report = f"✅ Рассылка завершена!\n\n"
            report += f"📊 Итоговая статистика:\n"
            report += f"✅ Успешно: {broadcast_info['sent_count']}\n"
            report += f"❌ Неудачно: {broadcast_info['failed_count']}\n"
            report += f"📈 Успешность: {success_rate:.1f}%\n"
            report += f"⏱️ Время выполнения: {duration:.1f} сек\n"
            
            if broadcast_info['failed_chats']:
                report += f"\n🚫 Ошибки:\n"
                for failed in broadcast_info['failed_chats'][:3]:
                    report += f"• {failed['chat_title']}: {failed['error']}\n"
                if len(broadcast_info['failed_chats']) > 3:
                    report += f"... и еще {len(broadcast_info['failed_chats']) - 3} ошибок"
            
            bot.edit_message_text(
                report,
                broadcast_info['chat_id'],
                broadcast_info['status_message_id']
            )
            
            # Сохраняем статистику в базу данных
            message_content = getattr(user_messages.get(broadcast_info['user_id']), 'text', '[медиа]')
            chat_ids = [chat['chat_id'] for chat in broadcast_info.get('chats', [])]
            
            db.save_message_history(
                broadcast_info['user_id'],
                message_content,
                chat_ids,
                broadcast_info['sent_count'],
                broadcast_info['failed_count']
            )
            
        except Exception as e:
            logger.error(f"Failed to send final report for {broadcast_id}: {str(e)}")
    
    def get_broadcast_status(self, broadcast_id: str) -> Optional[Dict]:
        """Получение статуса рассылки"""
        return self.active_broadcasts.get(broadcast_id)
    
    def cancel_broadcast(self, broadcast_id: str) -> bool:
        """Отмена активной рассылки"""
        broadcast_info = self.active_broadcasts.get(broadcast_id)
        if broadcast_info and broadcast_info['status'] == 'running':
            broadcast_info['status'] = 'cancelled'
            return True
        return False

class ChatValidator:
    """Класс для валидации данных чатов"""
    
    @staticmethod
    def validate_chat_id(chat_id_str: str) -> Tuple[bool, int, str]:
        """Валидация ID чата"""
        try:
            # Убираем пробелы и лишние символы
            chat_id_str = chat_id_str.strip()
            
            # Проверяем формат
            if not re.match(r'^-?\d+$', chat_id_str):
                return False, 0, "ID чата должен состоять только из цифр (с минусом для групп)"
            
            chat_id = int(chat_id_str)
            
            # Проверяем диапазоны
            if chat_id > 0:
                # Личные чаты
                if chat_id > 10**10:
                    return False, 0, "Слишком большой ID для личного чата"
            else:
                # Группы и каналы
                if chat_id > -1:
                    return False, 0, "ID группы/канала должен быть отрицательным"
                if chat_id < -10**12:
                    return False, 0, "Слишком большой по модулю ID"
            
            return True, chat_id, "ID корректен"
            
        except ValueError:
            return False, 0, "ID чата должен быть числом"
        except Exception as e:
            return False, 0, f"Ошибка валидации: {str(e)}"
    
    @staticmethod
    def validate_message_content(message) -> Tuple[bool, str]:
        """Валидация содержимого сообщения"""
        try:
            # Проверяем поддерживаемые типы
            supported_types = [
                'text', 'photo', 'document', 'video', 'audio', 
                'voice', 'video_note', 'sticker', 'animation'
            ]
            
            if message.content_type not in supported_types:
                return False, f"Тип сообщения '{message.content_type}' не поддерживается"
            
            # Проверяем размер текста
            if message.content_type == 'text' and len(message.text) > 4096:
                return False, "Текст сообщения слишком длинный (максимум 4096 символов)"
            
            # Проверяем подпись к медиа
            if hasattr(message, 'caption') and message.caption and len(message.caption) > 1024:
                return False, "Подпись к медиа слишком длинная (максимум 1024 символа)"
            
            return True, "Сообщение корректно"
            
        except Exception as e:
            return False, f"Ошибка валидации сообщения: {str(e)}"

# Инициализация менеджера рассылок
broadcast_manager = BroadcastManager()

class RecoveryManager:
    """Класс для восстановления после сбоев"""
    
    def __init__(self):
        self.recovery_file = "bot_recovery.json"
        self.load_recovery_data()
    
    def load_recovery_data(self):
        """Загрузка данных восстановления"""
        try:
            if os.path.exists(self.recovery_file):
                with open(self.recovery_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Восстанавливаем состояния пользователей
                    global user_states, user_messages
                    user_states.update(data.get('user_states', {}))
                    user_messages.update(data.get('user_messages', {}))
                    logger.info("Recovery data loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load recovery data: {str(e)}")
    
    def save_recovery_data(self):
        """Сохранение данных для восстановления"""
        try:
            data = {
                'user_states': user_states,
                'user_messages': {k: v for k, v in user_messages.items() 
                                if not k.endswith('_filtered')},  # Исключаем временные данные
                'timestamp': time.time()
            }
            
            with open(self.recovery_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save recovery data: {str(e)}")
    
    def cleanup_old_data(self):
        """Очистка старых данных восстановления"""
        try:
            if os.path.exists(self.recovery_file):
                with open(self.recovery_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    timestamp = data.get('timestamp', 0)
                    
                    # Удаляем данные старше 1 часа
                    if time.time() - timestamp > 3600:
                        os.remove(self.recovery_file)
                        logger.info("Old recovery data cleaned up")
        except Exception as e:
            logger.error(f"Failed to cleanup recovery data: {str(e)}")

class ChatMonitor:
    """Класс для мониторинга состояния чатов"""
    
    def __init__(self):
        self.check_interval = 300  # 5 минут
        self.monitoring_thread = None
        self.monitoring_active = False
    
    def start_monitoring(self):
        """Запуск мониторинга чатов"""
        if not self.monitoring_active:
            self.monitoring_active = True
            self.monitoring_thread = threading.Thread(target=self._monitor_chats, daemon=True)
            self.monitoring_thread.start()
            logger.info("Chat monitoring started")
    
    def stop_monitoring(self):
        """Остановка мониторинга"""
        self.monitoring_active = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)
        logger.info("Chat monitoring stopped")
    
    def _monitor_chats(self):
        """Основной цикл мониторинга"""
        while self.monitoring_active:
            try:
                self._check_inactive_chats()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in chat monitoring: {str(e)}")
                time.sleep(60)  # Пауза при ошибке
    
    def _check_inactive_chats(self):
        """Проверка неактивных чатов"""
        try:
            # Получаем все чаты из базы данных
            with sqlite3.connect(db.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT DISTINCT user_id, chat_id, chat_title, last_checked
                    FROM user_chats 
                    WHERE is_active = 1 
                    AND (last_checked IS NULL OR last_checked < datetime('now', '-1 hour'))
                    LIMIT 10
                ''')
                
                chats_to_check = cursor.fetchall()
                
                for user_id, chat_id, chat_title, last_checked in chats_to_check:
                    try:
                        # Проверяем доступность чата
                        is_admin, _ = ChatHelper.check_bot_admin_status(chat_id)
                        
                        # Обновляем статус в базе данных
                        db.update_chat_admin_status(user_id, chat_id, is_admin)
                        
                        logger.debug(f"Checked chat {chat_id}: {'admin' if is_admin else 'not admin'}")
                        
                        # Небольшая пауза между проверками
                        time.sleep(0.5)
                        
                    except Exception as e:
                        # Если чат недоступен, помечаем как неактивный
                        if "Forbidden" in str(e) or "chat not found" in str(e).lower():
                            cursor.execute('''
                                UPDATE user_chats 
                                SET is_active = 0, last_checked = CURRENT_TIMESTAMP
                                WHERE user_id = ? AND chat_id = ?
                            ''', (user_id, chat_id))
                            conn.commit()
                            logger.info(f"Marked chat {chat_id} as inactive: {str(e)}")
                        
                        time.sleep(1)  # Пауза при ошибке
                        
        except Exception as e:
            logger.error(f"Error checking inactive chats: {str(e)}")

# Инициализация систем восстановления и мониторинга
recovery_manager = RecoveryManager()
chat_monitor = ChatMonitor()

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
    
    @staticmethod
    def format_api_error(error_str: str) -> str:
        """Форматирование ошибок API для пользователя"""
        if "Forbidden" in error_str:
            if "bot was kicked" in error_str.lower():
                return "Бот был исключен из чата"
            elif "bot was blocked" in error_str.lower():
                return "Бот заблокирован пользователем"
            else:
                return "Нет доступа к чату"
        elif "Bad Request" in error_str:
            if "chat not found" in error_str.lower():
                return "Чат не найден или удален"
            elif "user not found" in error_str.lower():
                return "Пользователь не найден"
            elif "not enough rights" in error_str.lower():
                return "Недостаточно прав"
            elif "message is too long" in error_str.lower():
                return "Сообщение слишком длинное"
            else:
                return "Неверный запрос"
        elif "Too Many Requests" in error_str:
            return "Превышен лимит запросов (попробуйте позже)"
        elif "Network" in error_str or "timeout" in error_str.lower():
            return "Проблемы с сетью"
        elif "Internal Server Error" in error_str:
            return "Ошибка сервера Telegram"
        else:
            return f"Неизвестная ошибка: {error_str[:50]}"

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

@bot.callback_query_handler(func=lambda call: call.data.startswith('recheck_chat_'))
def recheck_chat_callback(call):
    """Повторная проверка статуса чата"""
    try:
        chat_id = int(call.data.split('_')[2])
        user_id = call.from_user.id
        
        # Проверяем статус
        is_admin, status_text = ChatHelper.check_bot_admin_status(chat_id)
        
        # Обновляем в базе данных
        db.update_chat_admin_status(user_id, chat_id, is_admin)
        
        bot.answer_callback_query(
            call.id, 
            f"✅ Статус обновлен: {'Админ' if is_admin else 'Не админ'}"
        )
        
        # Обновляем сообщение
        bot.edit_message_text(
            f"🔄 **Статус обновлен:**\n\n{status_text}",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == 'show_all_chats')
def show_all_chats_callback(call):
    """Показать все чаты через callback"""
    fake_message = call.message
    fake_message.from_user = call.from_user
    show_user_chats(fake_message)
    bot.answer_callback_query(call.id, "Список чатов обновлен")

@bot.callback_query_handler(func=lambda call: call.data.startswith('filter_'))
def filter_chats_callback(call):
    """Обработчик фильтрации чатов"""
    filter_type = call.data.split('_')[1]
    user_id = call.from_user.id
    
    if filter_type == "channel":
        filtered_chats = db.get_user_chats(user_id, only_admin=True)
        filtered_chats = [c for c in filtered_chats if c['chat_type'] == 'channel']
        filter_name = "каналы"
    elif filter_type == "groups":
        filtered_chats = db.get_user_chats(user_id, only_admin=True)
        filtered_chats = [c for c in filtered_chats if c['chat_type'] in ['group', 'supergroup']]
        filter_name = "группы"
    else:
        bot.answer_callback_query(call.id, "Неизвестный фильтр")
        return
    
    if not filtered_chats:
        bot.answer_callback_query(call.id, f"Нет доступных чатов типа '{filter_name}'")
        return
    
    # Обновляем список чатов для рассылки (временно сохраняем в состоянии)
    user_messages[f"{user_id}_filtered"] = filtered_chats
    
    bot.edit_message_text(
        f"✅ **Фильтр применен: {filter_name}**\n\n"
        f"📊 Выбрано чатов: {len(filtered_chats)}\n\n"
        f"Теперь рассылка будет отправлена только в эти чаты.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    
    bot.answer_callback_query(call.id, f"Применен фильтр: {filter_name}")

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_send')
def back_to_send_callback(call):
    """Возврат к отправке сообщения"""
    user_id = call.from_user.id
    
    # Восстанавливаем состояние подтверждения
    user_states[user_id] = UserStates.WAITING_FOR_CONFIRMATION
    
    keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    keyboard.add(
        types.KeyboardButton("✅ Отправить сейчас"),
        types.KeyboardButton("⚙️ Настройки рассылки")
    )
    keyboard.add(types.KeyboardButton("❌ Отмена"))
    
    bot.edit_message_text(
        "↩️ **Возврат к отправке**\n\nВыберите действие:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='Markdown'
    )
    
    bot.send_message(
        call.message.chat.id,
        "✅ **Подтвердите отправку:**",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )
    
    bot.answer_callback_query(call.id, "Возврат к отправке")

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
        # Обработка добавления чата с улучшенной валидацией
        
        # Валидация ID чата
        is_valid, chat_id, validation_message = ChatValidator.validate_chat_id(message.text)
        
        if not is_valid:
            bot.send_message(
                message.chat.id,
                f"❌ {validation_message}\n\n"
                "📝 Правильные форматы ID:\n"
                "• Личный чат: 123456789\n"
                "• Группа: -123456789\n"
                "• Супергруппа: -1001234567890\n"
                "• Канал: -1001234567890\n\n"
                "💡 Советы:\n"
                "• Используйте @userinfobot для получения ID\n"
                "• ID групп и каналов всегда отрицательные\n"
                "• Убедитесь, что скопировали ID полностью",
                reply_markup=create_cancel_keyboard()
            )
            return
        
        try:
            # Получаем информацию о чате
            chat_info = ChatHelper.get_chat_info(chat_id)
            
            if not chat_info:
                bot.send_message(
                    message.chat.id,
                    "❌ Не удалось получить информацию о чате.\n\n"
                    "🔧 Возможные решения:\n"
                    "1️⃣ Убедитесь, что бот добавлен в чат\n"
                    "2️⃣ Проверьте правильность ID чата\n"
                    "3️⃣ Для каналов: сделайте канал публичным временно\n"
                    "4️⃣ Проверьте, не заблокирован ли бот в чате\n\n"
                    "🔄 Попробуйте еще раз или используйте другой способ получения ID",
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
            
            # Формируем детальный ответ
            response = f"{'✅' if success else '⚠️'} **{result_message}**\n\n"
            response += f"📋 **Информация о чате:**\n"
            response += f"• **Название:** {chat_info['title']}\n"
            response += f"• **ID:** `{chat_id}`\n"
            response += f"• **Тип:** {ChatHelper.format_chat_type(chat_info['type'])}\n"
            
            if chat_info.get('username'):
                response += f"• **Username:** @{chat_info['username']}\n"
                
            if chat_info.get('member_count', 0) > 0:
                response += f"• **Участников:** {chat_info['member_count']}\n"
            
            if chat_info.get('description'):
                desc = chat_info['description'][:100]
                if len(chat_info['description']) > 100:
                    desc += "..."
                response += f"• **Описание:** {desc}\n"
            
            response += f"\n🔐 **Статус бота:**\n{admin_status}"
            
            # Рекомендации на основе статуса
            if not is_admin:
                response += "\n\n⚠️ **Важно:** Для корректной работы рассылки назначьте бота администратором с правами:\n"
                response += "• Отправка сообщений\n"
                response += "• Удаление сообщений (рекомендуется)\n"
                response += "• Закрепление сообщений (опционально)"
            else:
                response += "\n\n✅ **Отлично!** Чат готов для рассылки сообщений."
            
            # Создаем inline клавиатуру для быстрых действий
            keyboard = types.InlineKeyboardMarkup()
            if not is_admin:
                keyboard.add(types.InlineKeyboardButton(
                    "🔄 Перепроверить статус", 
                    callback_data=f"recheck_chat_{chat_id}"
                ))
            keyboard.add(types.InlineKeyboardButton(
                "📋 Показать все чаты", 
                callback_data="show_all_chats"
            ))
            
            bot.send_message(message.chat.id, response, 
                           reply_markup=keyboard, parse_mode='Markdown')
                
        except Exception as e:
            error_msg = ChatHelper.format_api_error(str(e))
            logger.error(f"Error adding chat {message.text}: {str(e)}")
            
            bot.send_message(
                message.chat.id,
                f"❌ **Ошибка при добавлении чата**\n\n"
                f"🔍 **Детали:** {error_msg}\n\n"
                f"🔄 **Что можно сделать:**\n"
                f"• Проверить правильность ID чата\n"
                f"• Убедиться, что бот добавлен в чат\n"
                f"• Попробовать еще раз через несколько минут\n"
                f"• Обратиться к администратору чата",
                reply_markup=create_main_keyboard(),
                parse_mode='Markdown'
            )
        
        user_states.pop(user_id, None)
        
    elif user_state == UserStates.WAITING_FOR_MESSAGE:
        # Валидация сообщения
        is_valid, validation_message = ChatValidator.validate_message_content(message)
        
        if not is_valid:
            bot.send_message(
                message.chat.id,
                f"❌ {validation_message}\n\n"
                "📝 Поддерживаемые типы:\n"
                "• Текст (до 4096 символов)\n"
                "• Изображения с подписью\n"
                "• Документы, видео, аудио\n"
                "• Голосовые сообщения\n"
                "• Стикеры и GIF\n\n"
                "Попробуйте отправить другое сообщение:",
                reply_markup=create_cancel_keyboard()
            )
            return
        
        # Получаем чаты где бот админ
        user_chats = db.get_user_chats(user_id, only_admin=True)
        
        if not user_chats:
            all_chats = db.get_user_chats(user_id)
            if not all_chats:
                bot.send_message(
                    message.chat.id,
                    "❌ **У вас нет подключенных чатов**\n\n"
                    "🔧 Что делать:\n"
                    "• Нажмите '➕ Добавить чат' для добавления\n"
                    "• Добавьте бота в нужные чаты как администратора\n"
                    "• Получите ID чатов и добавьте их в бот",
                    reply_markup=create_main_keyboard(),
                    parse_mode='Markdown'
                )
            else:
                admin_count = len([c for c in all_chats if c['bot_is_admin']])
                bot.send_message(
                    message.chat.id,
                    f"❌ **Нет чатов для рассылки**\n\n"
                    f"📊 **Статус ваших чатов:**\n"
                    f"• Всего подключено: {len(all_chats)}\n"
                    f"• Бот является админом: {admin_count}\n"
                    f"• Доступно для рассылки: {admin_count}\n\n"
                    f"🔧 **Решение:**\n"
                    f"• Используйте '🔍 Проверить чаты' для обновления\n"
                    f"• Назначьте бота администратором в нужных чатах\n"
                    f"• Проверьте права бота в настройках чатов",
                    reply_markup=create_main_keyboard(),
                    parse_mode='Markdown'
                )
            user_states.pop(user_id, None)
            return
        
        # Сохраняем сообщение для отправки
        user_messages[user_id] = message
        
        # Группируем чаты по типам для красивого отображения
        chat_groups = {}
        for chat in user_chats:
            chat_type = chat['chat_type']
            if chat_type not in chat_groups:
                chat_groups[chat_type] = []
            chat_groups[chat_type].append(chat)
        
        # Формируем превью с группировкой
        preview_text = f"📋 **Готово к отправке в {len(user_chats)} чат(ов):**\n\n"
        
        for chat_type, chats in chat_groups.items():
            type_emoji = {
                'group': '👥',
                'supergroup': '👥',
                'channel': '📢',
                'private': '👤'
            }.get(chat_type, '💬')
            
            preview_text += f"{type_emoji} **{ChatHelper.format_chat_type(chat_type)}** ({len(chats)}):\n"
            
            for chat in chats[:3]:  # Показываем первые 3 чата каждого типа
                preview_text += f"• {chat['chat_title']}\n"
            
            if len(chats) > 3:
                preview_text += f"• ... и еще {len(chats) - 3}\n"
            preview_text += "\n"
        
        # Информация о сообщении
        preview_text += f"📝 **Содержимое:**\n"
        
        if message.content_type == 'text':
            text_preview = message.text[:150]
            if len(message.text) > 150:
                text_preview += "..."
            preview_text += f"📄 Текст: {text_preview}\n"
        elif message.content_type == 'photo':
            preview_text += "🖼️ Изображение"
            if message.caption:
                cap_preview = message.caption[:80]
                if len(message.caption) > 80:
                    cap_preview += "..."
                preview_text += f" с подписью: {cap_preview}"
            preview_text += "\n"
        elif message.content_type == 'document':
            file_name = message.document.file_name or 'файл'
            file_size = message.document.file_size
            size_mb = file_size / (1024 * 1024) if file_size else 0
            preview_text += f"📁 Документ: {file_name}"
            if size_mb > 0:
                preview_text += f" ({size_mb:.1f} МБ)"
            preview_text += "\n"
        elif message.content_type == 'video':
            duration = getattr(message.video, 'duration', 0)
            preview_text += f"🎥 Видео"
            if duration > 0:
                preview_text += f" ({duration//60}:{duration%60:02d})"
            preview_text += "\n"
        elif message.content_type == 'audio':
            duration = getattr(message.audio, 'duration', 0)
            title = getattr(message.audio, 'title', 'аудио')
            preview_text += f"🎵 Аудио: {title}"
            if duration > 0:
                preview_text += f" ({duration//60}:{duration%60:02d})"
            preview_text += "\n"
        elif message.content_type == 'voice':
            duration = getattr(message.voice, 'duration', 0)
            preview_text += f"🎤 Голосовое"
            if duration > 0:
                preview_text += f" ({duration}с)"
            preview_text += "\n"
        elif message.content_type == 'sticker':
            emoji = getattr(message.sticker, 'emoji', '🎭')
            preview_text += f"{emoji} Стикер\n"
        else:
            preview_text += f"📎 {message.content_type.title()}\n"
        
        # Оценка времени рассылки
        estimated_time = len(user_chats) * 0.2  # примерно 0.2 сек на чат
        if estimated_time > 60:
            time_str = f"{estimated_time//60:.0f}м {estimated_time%60:.0f}с"
        else:
            time_str = f"{estimated_time:.0f}с"
        
        preview_text += f"\n⏱️ **Примерное время:** {time_str}\n"
        preview_text += f"📊 **Режим:** Умная рассылка с контролем скорости\n\n"
        preview_text += "✅ **Подтвердите отправку:**"
        
        user_states[user_id] = UserStates.WAITING_FOR_CONFIRMATION
        
        # Создаем расширенную клавиатуру подтверждения
        keyboard = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        keyboard.add(
            types.KeyboardButton("✅ Отправить сейчас"),
            types.KeyboardButton("⚙️ Настройки рассылки")
        )
        keyboard.add(types.KeyboardButton("❌ Отмена"))
        
        bot.send_message(message.chat.id, preview_text, 
                        reply_markup=keyboard, parse_mode='Markdown')
        
    elif user_state == UserStates.WAITING_FOR_CONFIRMATION:
        if message.text in ["✅ Отправить сейчас", "✅ Отправить"]:
            # Запускаем улучшенную массовую рассылку
            original_message = user_messages.get(user_id)
            if not original_message:
                bot.send_message(
                    message.chat.id,
                    "❌ **Ошибка:** сообщение не найдено. Попробуйте еще раз.",
                    reply_markup=create_main_keyboard(),
                    parse_mode='Markdown'
                )
                user_states.pop(user_id, None)
                return
            
            user_chats = db.get_user_chats(user_id, only_admin=True)
            
            if not user_chats:
                bot.send_message(
                    message.chat.id,
                    "❌ **Нет доступных чатов для рассылки**\n\n"
                    "Возможно, статус чатов изменился. Проверьте чаты и попробуйте снова.",
                    reply_markup=create_main_keyboard(),
                    parse_mode='Markdown'
                )
                user_states.pop(user_id, None)
                user_messages.pop(user_id, None)
                return
            
            # Создаем сообщение о начале рассылки
            status_message = bot.send_message(
                message.chat.id,
                f"🚀 **Запускаю умную рассылку...**\n\n"
                f"📋 Чатов для обработки: {len(user_chats)}\n"
                f"📊 Режим: Контроль скорости активен\n"
                f"⏱️ Начало: {datetime.now().strftime('%H:%M:%S')}",
                parse_mode='Markdown'
            )
            
            # Запускаем рассылку через BroadcastManager
            broadcast_id = broadcast_manager.start_broadcast(
                user_id, original_message, user_chats, 
                status_message.message_id, message.chat.id
            )
            
            # Очищаем состояние пользователя
            user_states.pop(user_id, None)
            user_messages.pop(user_id, None)
            
            # Отправляем главное меню
            bot.send_message(
                message.chat.id,
                "📤 **Рассылка запущена в фоновом режиме!**\n\n"
                "Вы получите уведомление о завершении.\n"
                "Можете продолжать пользоваться ботом.",
                reply_markup=create_main_keyboard(),
                parse_mode='Markdown'
            )
            
        elif message.text == "⚙️ Настройки рассылки":
            # Показываем настройки рассылки
            settings_text = "⚙️ **Настройки рассылки:**\n\n"
            
            user_chats = db.get_user_chats(user_id, only_admin=True)
            chat_groups = {}
            for chat in user_chats:
                chat_type = chat['chat_type']
                if chat_type not in chat_groups:
                    chat_groups[chat_type] = []
                chat_groups[chat_type].append(chat)
            
            settings_text += "📊 **Доступные фильтры:**\n"
            for chat_type, chats in chat_groups.items():
                type_name = ChatHelper.format_chat_type(chat_type)
                settings_text += f"• {type_name}: {len(chats)} чат(ов)\n"
            
            settings_text += "\n🔧 **Выберите действие:**"
            
            keyboard = types.InlineKeyboardMarkup()
            keyboard.add(types.InlineKeyboardButton(
                "📢 Только каналы", callback_data="filter_channel"
            ))
            keyboard.add(types.InlineKeyboardButton(
                "👥 Только группы", callback_data="filter_groups"
            ))
            keyboard.add(types.InlineKeyboardButton(
                "🎯 Выбрать чаты", callback_data="select_chats"
            ))
            keyboard.add(types.InlineKeyboardButton(
                "↩️ Назад к отправке", callback_data="back_to_send"
            ))
            
            bot.send_message(message.chat.id, settings_text, 
                           reply_markup=keyboard, parse_mode='Markdown')
            
        else:
            # Отмена отправки
            user_states.pop(user_id, None)
            user_messages.pop(user_id, None)
            bot.send_message(
                message.chat.id,
                "❌ **Отправка отменена**\n\n"
                "Сообщение не было отправлено в чаты.",
                reply_markup=create_main_keyboard(),
                parse_mode='Markdown'
            )
        
    else:
        # Обычное состояние - показываем помощь
        bot.send_message(
            message.chat.id,
            "Используйте кнопки меню для взаимодействия с ботом.\nДля получения помощи нажмите 'ℹ️ Помощь'",
            reply_markup=create_main_keyboard()
        )

def save_state_periodically():
    """Периодическое сохранение состояния"""
    while True:
        try:
            time.sleep(30)  # Сохраняем каждые 30 секунд
            recovery_manager.save_recovery_data()
        except Exception as e:
            logger.error(f"Error saving state: {str(e)}")

def cleanup_and_exit():
    """Корректное завершение работы"""
    logger.info("Shutting down bot...")
    
    # Останавливаем мониторинг
    chat_monitor.stop_monitoring()
    
    # Сохраняем состояние
    recovery_manager.save_recovery_data()
    
    # Очищаем старые данные
    recovery_manager.cleanup_old_data()
    
    logger.info("Bot shutdown complete")

if __name__ == "__main__":
    logger.info("🚀 Запуск улучшенного телеграм бота...")
    
    try:
        # Запускаем мониторинг чатов
        chat_monitor.start_monitoring()
        
        # Запускаем поток автосохранения
        save_thread = threading.Thread(target=save_state_periodically, daemon=True)
        save_thread.start()
        
        logger.info("✅ Все системы запущены успешно")
        logger.info("📊 Активные компоненты:")
        logger.info("   • Основной бот")
        logger.info("   • Система рассылок")
        logger.info("   • Мониторинг чатов")
        logger.info("   • Система восстановления")
        logger.info("   • Автосохранение состояний")
        
        # Основной цикл бота
        bot.infinity_polling(none_stop=True)
        
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
        cleanup_and_exit()
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        cleanup_and_exit()
        raise
    finally:
        cleanup_and_exit()