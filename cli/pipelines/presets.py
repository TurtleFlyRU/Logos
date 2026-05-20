"""Пресеты переменных окружения для сборщика контекста (фаза 9b).

Каждый пресет — набор временных переопределений ``os.environ`` на время выполнения
пайплайна (через :func:`pipeline_preset`). Имена не совпадают с ``EIDOS_CHAT_*`` без
повода; значения строковые как в окружении.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

_PIPELINE_PRESETS: dict[str, dict[str, str]] = {
    "research": {
        "EIDOS_CHAT_WM_MESSAGES": "56",
        "EIDOS_CHAT_ACTIVE_MEMORY_CHARS": "16000",
        "EIDOS_CHAT_MEMORY_PIPELINE": "full",
    },
    "experiment": {
        "EIDOS_CHAT_WM_MESSAGES": "44",
        "EIDOS_CHAT_ACTIVE_MEMORY_CHARS": "12000",
        "EIDOS_CHAT_MEMORY_PIPELINE": "full",
        "EIDOS_CHAT_BOOT_SNIPPET": "1",
        "EIDOS_TOOLS": "0",
    },
    "code_review": {
        "EIDOS_CHAT_WM_MESSAGES": "24",
        "EIDOS_CHAT_MEMORY_PIPELINE": "episodic_only",
        "EIDOS_CHAT_ACTIVE_MEMORY_CHARS": "8000",
        "EIDOS_TOOLS": "0",
    },
}


@contextmanager
def pipeline_preset(preset_name: str | None) -> Iterator[None]:
    """Временно применить пресет; при выходе восстановить прежние значения ключей.

    Args:
        preset_name: Ключ из внутреннего словаря пресетов или None (без изменений).
    """
    if not preset_name:
        yield
        return
    overrides = _PIPELINE_PRESETS.get(preset_name)
    if overrides is None:
        yield
        return
    saved: dict[str, str | None] = {}
    try:
        for key, val in overrides.items():
            saved[key] = os.environ.get(key)
            os.environ[key] = val
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def preset_names() -> tuple[str, ...]:
    """Имена зарегистрированных пресетов (для подсказок и тестов)."""
    return tuple(sorted(_PIPELINE_PRESETS.keys()))
