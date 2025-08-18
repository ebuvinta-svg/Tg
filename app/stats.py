from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Set


@dataclass
class RuntimeStats:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_messages: int = 0
    unique_user_ids: Set[int] = field(default_factory=set)

    def mark_started(self) -> None:
        self.started_at = datetime.now(timezone.utc)

    def register_message(self, user_id: int | None) -> None:
        self.total_messages += 1
        if user_id is not None:
            self.unique_user_ids.add(user_id)


STATS = RuntimeStats()
