from __future__ import annotations

from typing import Iterable

from aiogram.filters import BaseFilter
from aiogram.types import Message


class AdminFilter(BaseFilter):
    def __init__(self, admin_ids: Iterable[int]) -> None:
        self._admins = set(admin_ids)

    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in self._admins)


class ChatAdminOnly(BaseFilter):
    def __init__(self) -> None:
        pass

    async def __call__(self, message: Message) -> bool:
        if message.chat.type not in {"group", "supergroup"}:
            return False
        if not message.from_user:
            return False
        try:
            member = await message.bot.get_chat_member(chat_id=message.chat.id, user_id=message.from_user.id)
            return member.status in {"administrator", "creator"}
        except Exception:
            return False

