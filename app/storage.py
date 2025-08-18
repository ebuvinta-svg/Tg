from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ChatSettings:
    welcome_enabled: bool = True
    welcome_text: str = "Добро пожаловать!"
    rules_text: str = "Правила чата пока не заданы."
    slowmode_seconds: int = 0
    pin_welcome: bool = False


class InMemoryStorage:
    def __init__(self) -> None:
        self.chat_id_to_settings: Dict[int, ChatSettings] = {}

    def get_chat_settings(self, chat_id: int) -> ChatSettings:
        return self.chat_id_to_settings.setdefault(chat_id, ChatSettings())

    def set_welcome(self, chat_id: int, enabled: bool, text: Optional[str] = None, pin: Optional[bool] = None) -> ChatSettings:
        settings = self.get_chat_settings(chat_id)
        settings.welcome_enabled = enabled
        if text is not None:
            settings.welcome_text = text
        if pin is not None:
            settings.pin_welcome = pin
        return settings

    def set_rules(self, chat_id: int, text: str) -> ChatSettings:
        settings = self.get_chat_settings(chat_id)
        settings.rules_text = text
        return settings

    def set_slowmode(self, chat_id: int, seconds: int) -> ChatSettings:
        settings = self.get_chat_settings(chat_id)
        settings.slowmode_seconds = max(0, seconds)
        return settings


STORAGE = InMemoryStorage()
