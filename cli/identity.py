"""Имя пользователя из явных фраз в CLI → WM context."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"меня\s+зовут\s+([А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{1,48})", re.I),
    re.compile(r"my\s+name\s+is\s+([A-Za-zА-Яа-яЁё][А-Яа-яЁёA-Za-z\-]{1,48})", re.I),
    re.compile(r"(?:^|[\s,.!?])я\s*[—\-]\s*([А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\-]{1,48})(?:\s|$|[,.!?])", re.I),
)


def try_capture_user_display_name(memory: Any, line: str) -> None:
    text = line.strip()
    if len(text) < 4:
        return
    for rx in _PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        name = str(m.group(1)).strip()
        if 2 <= len(name) <= 60:
            memory.working.set_context("user_display_name", name)
        return
