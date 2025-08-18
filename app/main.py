from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage

from .config import load_settings
from .handlers import create_admin_router, create_public_router
from .logging_setup import configure_logging
from .middlewares import SimpleRateLimiter, ActivityTrackingMiddleware


async def _on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logging.getLogger(__name__).info("Bot started as @%s (%s)", me.username, me.id)
    # Set command descriptions for better discoverability
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Приветствие"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="ping", description="Проверка отклика"),
            BotCommand(command="echo", description="Повторить текст"),
            BotCommand(command="id", description="Мой ID и ID чата"),
            BotCommand(command="stats", description="Статистика"),
        ])
    except Exception:
        pass


async def _create_dispatcher(settings) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(ActivityTrackingMiddleware())
    dp.update.middleware(SimpleRateLimiter(requests_per_user_per_minute=30))
    dp.include_router(create_public_router())
    dp.include_router(create_admin_router(settings.admins))
    return dp


async def run() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)
    dp = await _create_dispatcher(settings)

    await _on_startup(bot)
    # Global error logging
    @dp.errors()
    async def on_error(event, exception):
        logging.getLogger(__name__).exception("Unhandled error: %s", exception)
        return True

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("Bot stopped")


if __name__ == "__main__":
    main()
