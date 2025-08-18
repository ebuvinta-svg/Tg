from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Dict
from collections import deque

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, Update


logger = logging.getLogger(__name__)


@dataclass
class RateLimitRule:
    max_calls: int
    time_window_seconds: float


class SimpleRateLimiter(BaseMiddleware):
    def __init__(self, requests_per_user_per_minute: int = 20) -> None:
        super().__init__()
        self.user_to_timestamps: Dict[int, deque[float]] = {}
        self.rule = RateLimitRule(
            max_calls=requests_per_user_per_minute,
            time_window_seconds=60.0,
        )

    async def __call__(self, handler: Callable, event: TelegramObject, data: Dict):
        update: Update | None = data.get("event_update")

        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif update and update.event and getattr(update.event, "from_user", None):
            user_id = update.event.from_user.id  # type: ignore[attr-defined]

        if user_id is None:
            return await handler(event, data)

        timestamps = self.user_to_timestamps.setdefault(user_id, deque())
        now = asyncio.get_running_loop().time()

        # Prune timestamps outside the window
        window_start = now - self.rule.time_window_seconds
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= self.rule.max_calls:
            logger.debug("Rate limit exceeded for user %s", user_id)
            return  # Drop silently

        timestamps.append(now)
        return await handler(event, data)
