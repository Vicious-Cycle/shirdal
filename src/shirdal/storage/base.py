from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CachedChat:
    chat_id: int
    chat_type: str = "private"
    title: str | None = None
    username: str | None = None
    extra: dict[str, Any] | None = None
    expires_at: float | None = None
