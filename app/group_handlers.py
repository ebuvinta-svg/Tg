from __future__ import annotations

import asyncio
import logging
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

from .filters import ChatAdminOnly
from .storage import STORAGE


logger = logging.getLogger(__name__)


def create_group_router() -> Router:
    router = Router(name="group")

    # Apply only in groups
    router.message.filter(F.chat.type.in_({"group", "supergroup"}))

    @router.message(Command(commands=["settings"]))
    async def cmd_settings(message: Message) -> None:
        s = STORAGE.get_chat_settings(message.chat.id)
        await message.reply(
            "Настройки чата:\n"
            f"Welcome: {'включен' if s.welcome_enabled else 'выключен'}\n"
            f"Pin welcome: {'да' if s.pin_welcome else 'нет'}\n"
            f"Slowmode: {s.slowmode_seconds} сек\n"
            f"Rules: {('заданы' if s.rules_text else 'не заданы')}"
        )

    @router.message(ChatAdminOnly(), Command(commands=["welcome"]))
    async def cmd_welcome(message: Message, command: CommandObject) -> None:
        # Usage: /welcome on|off [--pin] [текст]
        args = (command.args or "").strip()
        enable = None
        pin = None
        text: Optional[str] = None
        if args:
            parts = args.split()
            if parts and parts[0].lower() in {"on", "off"}:
                enable = parts[0].lower() == "on"
                parts = parts[1:]
            if parts and parts[0] == "--pin":
                pin = True
                parts = parts[1:]
            if parts:
                text = " ".join(parts)
        if enable is None:
            await message.reply("Использование: /welcome on|off [--pin] [текст]")
            return
        s = STORAGE.set_welcome(message.chat.id, enable, text=text, pin=pin)
        await message.reply(
            f"Welcome {'включен' if s.welcome_enabled else 'выключен'}\nТекст: {s.welcome_text}\nPin: {'да' if s.pin_welcome else 'нет'}"
        )

    @router.message(ChatAdminOnly(), Command(commands=["rules"]))
    async def cmd_rules(message: Message, command: CommandObject) -> None:
        text = (command.args or "").strip()
        if not text:
            await message.reply("Использование: /rules <текст правил>")
            return
        STORAGE.set_rules(message.chat.id, text)
        await message.reply("Правила обновлены ✅")

    @router.message(Command(commands=["getrules"]))
    async def cmd_getrules(message: Message) -> None:
        s = STORAGE.get_chat_settings(message.chat.id)
        await message.reply(s.rules_text or "Правила не заданы")

    @router.message(ChatAdminOnly(), Command(commands=["slowmode"]))
    async def cmd_slowmode(message: Message, command: CommandObject) -> None:
        arg = (command.args or "").strip()
        if not arg.isdigit():
            await message.reply("Использование: /slowmode <секунды> (0 чтобы отключить)")
            return
        seconds = int(arg)
        STORAGE.set_slowmode(message.chat.id, seconds)
        await message.reply(f"Slowmode установлен: {seconds} сек")

    @router.message(ChatAdminOnly(), Command(commands=["warn"]))
    async def cmd_warn(message: Message) -> None:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply("Ответьте на сообщение нарушителя командой /warn")
            return
        user = message.reply_to_message.from_user
        await message.reply(f"Предупреждение выдано: {user.full_name}")

    @router.message(ChatAdminOnly(), Command(commands=["mute"]))
    async def cmd_mute(message: Message, command: CommandObject) -> None:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply("Ответьте на сообщение нарушителя командой /mute <минуты>")
            return
        mins = 10
        arg = (command.args or "").strip()
        if arg.isdigit():
            mins = int(arg)
        until_date = message.date + (mins * 60)
        try:
            await message.bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=message.reply_to_message.from_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
            await message.reply(f"Мут: {mins} минут")
        except Exception:
            await message.reply("Не удалось замьютить пользователя")

    @router.message(ChatAdminOnly(), Command(commands=["ban"]))
    async def cmd_ban(message: Message) -> None:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.reply("Ответьте на сообщение нарушителя командой /ban")
            return
        try:
            await message.bot.ban_chat_member(
                chat_id=message.chat.id,
                user_id=message.reply_to_message.from_user.id,
            )
            await message.reply("Пользователь забанен")
        except Exception:
            await message.reply("Не удалось забанить пользователя")

    @router.message(ChatAdminOnly(), Command(commands=["pin"]))
    async def cmd_pin(message: Message) -> None:
        if not message.reply_to_message:
            await message.reply("Ответьте на сообщение, которое нужно закрепить, командой /pin")
            return
        try:
            await message.bot.pin_chat_message(chat_id=message.chat.id, message_id=message.reply_to_message.message_id)
            await message.reply("Сообщение закреплено")
        except Exception:
            await message.reply("Не удалось закрепить сообщение")

    return router

