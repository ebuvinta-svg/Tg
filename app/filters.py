from __future__ import annotations

from typing import Iterable

from aiogram.filters import BaseFilter
from aiogram.types import Message


class AdminFilter(BaseFilter):
    def __init__(self, admin_ids: Iterable[int]) -> None:
        self._admins = set(admin_ids)

    async def __call__(self, message: Message) -> bool:
        return bool(message.from_user and message.from_user.id in self._admins)

