"""Оценка значимости эпизода — что важно, что отложить."""

import json
import time
from typing import Any


def evaluate_salience(episode: dict[str, Any]) -> float:
    """Вычисляет значимость эпизода (0.0–1.0) на основе факторов."""

    score = 0.3  # базовый уровень

    # Фактор 1: свежесть (новые эпизоды важнее)
    age_hours = (time.time() - episode.get("timestamp", 0)) / 3600
    freshness = max(0.0, 1.0 - age_hours / 720)  # значимость падает за 30 дней
    score += freshness * 0.2

    # Фактор 2: длина (очень короткие записи — шум)
    raw_len = len(episode.get("raw_text", "") or "")
    if raw_len > 50:
        score += 0.1
    if raw_len > 500:
        score += 0.1

    # Фактор 3: теги (наличие ключевых тегов повышает значимость)
    tags = episode.get("tags", "[]")
    if isinstance(tags, str):
        try:
            tags_list = json.loads(tags)
        except json.JSONDecodeError:
            tags_list = tags.strip("[]").replace('"', "").split(",")
    else:
        tags_list = tags
    high_importance_tags = {"архитектура", "решение", "эксперимент", "инсайт", "ошибка"}
    if any(str(t).strip() in high_importance_tags for t in tags_list):
        score += 0.2

    # Фактор 4: результат применения. Ошибки и успешные решения стоит удерживать дольше.
    outcome = str(episode.get("outcome", "")).lower()
    if outcome in {"success", "ok", "passed", "решено"}:
        score += 0.1
    if outcome in {"error", "failed", "ошибка"}:
        score += 0.2

    # Фактор 5: ссылки на другие эпизоды
    linked = episode.get("linked_episodes", "[]")
    if isinstance(linked, str):
        linked_list = linked.strip("[]").split(",") if linked.strip("[]") else []
    else:
        linked_list = linked
    if linked_list:
        score += 0.1

    return min(1.0, max(0.0, score))
