from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message


logger = logging.getLogger(__name__)


def create_public_router() -> Router:
    router = Router(name="public")

    @router.message(Command(commands=["start"]))
    async def cmd_start(message: Message) -> None:
        await message.answer(
            "Привет! Я улучшенный бот. Напиши /help чтобы узнать, что я умею."
        )

    @router.message(Command(commands=["help"]))
    async def cmd_help(message: Message) -> None:
        await message.answer(
            "Доступные команды:\n"
            "/start — приветствие\n"
            "/help — помощь\n"
            "/ping — проверить отклик\n"
            "/echo <текст> — повторить текст"
        )

    @router.message(Command(commands=["ping"]))
    async def cmd_ping(message: Message) -> None:
        started_at = datetime.now()
        reply = await message.answer("Pong!")
        latency_ms = (datetime.now() - started_at).total_seconds() * 1000
        await reply.edit_text(f"Pong! {latency_ms:.0f} ms")

    @router.message(Command(commands=["echo"]))
    async def cmd_echo(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Укажите текст: /echo <текст>")
            return
        await message.answer(command.args)

    @router.message(F.text)
    async def any_text(message: Message) -> None:
        logger.info("Message from %s: %s", message.from_user.id if message.from_user else None, message.text)
        await message.answer("Не понял. Напиши /help")

    return router


def create_admin_router(admin_ids: List[int]) -> Router:
    router = Router(name="admin")

    @router.message(Command(commands=["admin"]))
    async def cmd_admin(message: Message) -> None:
        if not message.from_user or message.from_user.id not in admin_ids:
            await message.answer("Только для админов")
            return
        await message.answer("Админка доступна. Все работает ✅")

    return router
