#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт запуска телеграм бота
"""

import os
import sys
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Проверяем наличие токена
if not os.getenv('BOT_TOKEN'):
    print("❌ Ошибка: не найден токен бота!")
    print("Создайте файл .env и добавьте в него:")
    print("BOT_TOKEN=ваш_токен_бота")
    print("\nТокен можно получить у @BotFather в Telegram")
    sys.exit(1)

# Импортируем и запускаем бота
try:
    from telegram_bot import bot, logger
    logger.info("🚀 Запуск бота...")
    print("🚀 Бот запущен! Нажмите Ctrl+C для остановки")
    bot.infinity_polling(none_stop=True)
except KeyboardInterrupt:
    print("\n⏹️ Бот остановлен пользователем")
except Exception as e:
    print(f"❌ Критическая ошибка: {e}")
    sys.exit(1)