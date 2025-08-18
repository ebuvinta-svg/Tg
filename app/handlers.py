from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, ContentType
from aiogram.utils.chat_action import ChatActionSender
from .stats import STATS
from .filters import AdminFilter


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
            "/echo <текст> — повторить текст\n"
            "/id — ваш ID и ID чата\n"
            "/stats — статистика"
        )

    @router.message(Command(commands=["ping"]))
    async def cmd_ping(message: Message) -> None:
        async with ChatActionSender.typing(chat_id=message.chat.id):
            started_at = datetime.now(timezone.utc)
            reply = await message.answer("Pong!")
        latency_ms = (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
        await reply.edit_text(f"Pong! {latency_ms:.0f} ms")

    @router.message(Command(commands=["echo"]))
    async def cmd_echo(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Укажите текст: /echo <текст>")
            return
        await message.answer(command.args)

    # Reply with info for common attachments
    @router.message(F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT, ContentType.VIDEO}))
    async def any_media(message: Message) -> None:
        await message.reply("Медиа получено ✅")

    @router.message(F.text)
    async def any_text(message: Message) -> None:
        logger.info("Message from %s: %s", message.from_user.id if message.from_user else None, message.text)
        if message.chat.type == "private":
            await message.answer("Не понял. Напиши /help")

    return router


def create_admin_router(admin_ids: List[int]) -> Router:
    router = Router(name="admin")
    router.message.filter(AdminFilter(admin_ids))

    @router.message(Command(commands=["admin"]))
    async def cmd_admin(message: Message) -> None:
        await message.answer("Админка доступна. Все работает ✅")

    @router.message(Command(commands=["broadcast"]))
    async def cmd_broadcast(message: Message, command: CommandObject) -> None:
        if not command.args:
            await message.answer("Использование: /broadcast <текст>")
            return
        # Flags: --silent (disable notifications), --parse=HTML|Markdown
        args = command.args
        silent = "--silent" in args
        parse = None
        if "--parse=" in args:
            try:
                parse = args.split("--parse=")[1].split()[0].upper()
            except Exception:
                parse = None
        text = args.replace("--silent", "")
        if parse:
            text = text.replace(f"--parse={parse}", "")
        text = text.strip()
        sent = 0
        errors = 0
        # Send in small batches to avoid hitting limits
        uids = list(STATS.unique_user_ids)
        chunk_size = 25
        for i in range(0, len(uids), chunk_size):
            chunk = uids[i:i+chunk_size]
            for uid in chunk:
                try:
                    await message.bot.send_message(uid, text, disable_notification=silent, parse_mode=parse)
                    sent += 1
                except Exception:
                    errors += 1
            # Tiny pause between chunks
            try:
                from asyncio import sleep
                await sleep(0.2)
            except Exception:
                pass
        await message.answer(f"Рассылка завершена. Успешно: {sent}, ошибок: {errors}.")

    @router.message(Command(commands=["stats"]))
    async def cmd_stats(message: Message) -> None:
        now = datetime.now(timezone.utc)
        uptime = now - STATS.started_at
        users = len(STATS.unique_user_ids)
        await message.answer(
            "Статистика бота:\n"
            f"Аптайм: {uptime}\n"
            f"Сообщений обработано: {STATS.total_messages}\n"
            f"Уникальных пользователей: {users}"
        )

    @router.message(Command(commands=["id"]))
    async def cmd_id(message: Message) -> None:
        uid = message.from_user.id if message.from_user else None
        cid = message.chat.id
        await message.answer(f"Ваш ID: {uid}\nЧат ID: {cid}")

    return router
