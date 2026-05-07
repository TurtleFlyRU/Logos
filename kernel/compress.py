"""Компрессия длинного контекста — сжатие низкозначимых эпизодов."""

import re
from typing import Any


def compress_episode(episode: dict[str, Any]) -> str:
    """Сжимает эпизод: извлекает ключевые фразы, отбрасывает шум."""

    raw = episode.get("raw_text", "") or ""

    if not raw:
        return ""

    sentences = re.split(r'(?<=[.!?])\s+', raw)

    # Фильтр: короткие предложения — шум
    meaningful = [s for s in sentences if len(s) > 40]

    # Берём первые 3 осмысленных предложения + последнее
    if len(meaningful) <= 4:
        compressed = meaningful
    else:
        compressed = meaningful[:3] + [meaningful[-1]]

    return " ".join(compressed)


def summarize_working(events: list[dict[str, Any]], max_events: int = 10) -> list[dict[str, Any]]:
    """Суммаризирует рабочую память: оставляет только ключевые события."""
    if len(events) <= max_events:
        return events

    # Оставляем первые 3 + последние max_events - 3
    return events[:3] + events[-(max_events - 3):]
